"""
Author: Alex Walter
Date: Sept 4, 2018

This class is a container for the widesweep and powersweep data.
It can load a previous sweep, or take a new one.



TODO:
 - change configs to new format
 - 

"""


import traceback, sys, warnings, random
from functools import partial
import ConfigParser
from multiprocessing import Pool
import threading
import numpy as np
import matplotlib.pyplot as plt

from mkidreadout.utils.readDict import readDict
from mkidreadout.channelizer.RoachStateMachine import RoachStateMachine
from mkidreadout.channelizer.Roach2Controls import Roach2Controls


def setupMultRoaches4FreqSweep(roachNums, freqFN='rfFreqs.txt', defineLUTs=False):
    """
    calls setupRoach4FreqSweep() in different threads so that multiple roaches can be setup simultaneously

    Can't return anything because Roach2Controls isn't pickleable. 
    """
    func=partial(setupRoach4FreqSweep,freqFN=freqFN, defineLUTs=defineLUTs)
    p=Pool(min(len(roachNums),5))   #Will crash if there are too many
    p.map_async(func, roachNums)   #blocks until all threads finish
    p.close()
    p.join()


def writeDacAtten(roachNum, atten):
    fn = '.dacAtten_'+str(roachNum)
    with open(fn,'w') as f:
        f.write(str(atten))
        #f.close() #automatically closes in with statement

def getDacAtten(roachNum):
    fn = '.dacAtten_'+str(roachNum)
    atten=None
    with open(fn, "r") as f:
        atten=float(f.read())
    return atten

def setupRoach4FreqSweep(roachNum, freqFN='rfFreqs.txt', defineLUTs=False):
    """
    This function sets up the roach so that it is ready for sweeping. 
    Defining the LUTs can take a while, so avoid it if possible

    This function sets the globalDacAtten attribute in the returned Roach2Controls object

    INPUTS:
        roachNum - The last part of the roach ip. eg. 10.0.0.220 has roachNum=220
        freqFN - name of file with RF freqs (should be centered around 0 in Hz). Also has resID and attenuation
        defineLUTs - Boolean to redefine the DAC/DDC LUTs. You only need to do this once
    OUTPUTS:
        Roach2Controls object
        returns -1 if there's an error
    """
    try: 
        FPGAParamFile = '/home/mecvnc/MKIDReadout/mkidreadout/channelizer/darknessfpga.param'
        ip = '10.0.0.'+str(roachNum)
        roachController = Roach2Controls(ip,FPGAParamFile,True,False)

        #connect
        roachController.connect()
        if defineLUTs:
            ddsShift = roachController.checkDdsShift()
            roachController.loadDdsShift(ddsShift)
            roachController.loadFullDelayCal()

        #loadFreqs
        freqFile = np.loadtxt(freqFN)
        resIDs = np.atleast_1d(freqFile[:,0])
        freqs = np.atleast_1d(freqFile[:,1])
        attens = np.atleast_1d(freqFile[:,2])
        phaseOffsList = np.zeros(len(freqs))
        iqRatioList = np.ones(len(freqs))
        try:
            phaseOffsList = np.atleast_1d(freqFile[:,3])
            iqRatioList = np.atleast_1d(freqFile[:,4])
        except IndexError: pass

        #assert(len(resIDs) == len(np.unique(resIDs))), "Resonator IDs in "+fn+" need to be unique."
        argsSorted = np.argsort(freqs)  # sort them by frequency (Should already be sorted but just in case)
        freqs = freqs[argsSorted]
        resIDs = resIDs[argsSorted]
        attens = attens[argsSorted]
        phaseOffsList = iqRatioList[argsSorted]
        iqRatioList = iqRatioList[argsSorted]

        roachController.generateResonatorChannels(freqs)
        roachController.setAttenList(attens)
        roachController.resIDs = resIDs
        roachController.phaseOffsList = phaseOffsList
        roachController.iqRatioList = iqRatioList

        #defineRoachLUTs
        loFreq=0.
        roachController.setLOFreq(loFreq)   #Doesn't load it into LO chip. Just sets it in software
        roachController.generateFftChanSelection()
        if defineLUTs:
            roachController.generateDdsTones()
            roachController.loadChanSelection()
            roachController.loadDdsLUT()
        else:
            dacFreqList = roachController.freqList-loFreq
            dacFreqList[np.where(dacFreqList<0.)] += roachController.params['dacSampleRate']
            dacFreqResolution = roachController.params['dacSampleRate']/(roachController.params['nDacSamplesPerCycle']*roachController.params['nLutRowsToUse'])
            dacQuantizedFreqList = np.round(dacFreqList/dacFreqResolution)*dacFreqResolution
            roachController.dacQuantizedFreqList=dacQuantizedFreqList
        
        #defineDacLUTs
        loFreq=random.random()*2.-1.+5000.+2000.*roachNum%2    #Around 5000MHz for even roaches, 7000MHz for odd roaches. Should really specify based on low or high band of feedline since roach numbers are arbitrary. Although, with MEC even/odd numbers are low/high band. 
        if defineLUTs:
            combDict = roachController.generateDacComb()
            dacAtten=combDict['dacAtten']
            writeDacAtten(roachNum, dacAtten)   #Need this for powersweeps
            roachController.initializeV7UART()
        else:
            dacAtten=getDacAtten(roachNum)   #Need this for powersweeps
        roachController.globalDacAtten=dacAtten   #Need this for powersweeps
        roachController.loadLOFreq(loFreq)   
        if defineLUTs:
            roachController.loadDacLUT()
            roachController.changeAtten(1,np.floor(dacAtten*2)/4.)
            roachController.changeAtten(2,np.ceil(dacAtten*2)/4.)
            roachController.getOptimalADCAtten(15.) #arbitrary initial guess
        
        return roachController
    except:
        exc_info=sys.exc_info()
        print str(roachNum)+" ERROR"
        traceback.print_exception(*exc_info)
        del exc_info
        return None

def generateWidesweepFreqList(FPGAparams, outputFN='rfFreqs.txt', resAtten=65, alias_BW=1600.E6, lo_hole=512.E3, tone_BW=512.0E3, minNominalFreqSpacing=800.0E3):
    """
    Creates a frequency list for a widesweep centered around 0Hz.     

    INPUTS:
        FPGAparams: filename to fpga parameter file
        outputFN: name of output file
        resAtten: resonator attenuation (65 is good for MEC)
        alias_BW: bandwidth of antialiasing filter. (a little less than 2GHz). Will be clipped to the DAC bandwidth in the fpga file
        lo_hole: freq hole around LO that we should avoid
        tone_BW: bandwidth around tone to avoid crosstalk in FFT/DDS
        minNominalFreqSpacing: The number of tones should be <= alias_BW/minNominalFreqSpacing. Will be clipped to the number of channels supported by the firmware. 
    """
    try:
        params = readDict()             
        params.readFromFile(FPGAparams)
    except TypeError:
        params = paramFile
    max_BW = int(params['dacSampleRate'])
    alias_BW = min(alias_BW, max_BW)
    freqResolution = params['dacSampleRate']/(params['nDacSamplesPerCycle']*params['nLutRowsToUse'])
    minNominalFreqSpacing = max(tone_BW+100.*freqResolution, minNominalFreqSpacing)
    nChannels=params['nChannels']
    avgSpacing = (alias_BW - tone_BW)/nChannels
    if avgSpacing < (minNominalFreqSpacing):
        avgSpacing = minNominalFreqSpacing
        nChannels = int ((alias_BW - tone_BW)/avgSpacing)
    if nChannels<=1:
        nChannels=1
        avgSpacing=0.
    lo=0.
    
    freqs_low=makeRandomFreqSideband(0.-alias_BW/2.+freqResolution/2., -lo_hole/2.-freqResolution/2., np.ceil(nChannels/2.), tone_BW, freqResolution)
    freqs_high=makeRandomFreqSideband(lo_hole/2.+freqResolution/2., alias_BW/2.-freqResolution/2., np.floor(nChannels/2.), tone_BW, freqResolution)
    freqs = np.append(freqs_low, freqs_high)
    
    resIDs=np.asarray(range(len(freqs)))
    attens=np.asarray([np.rint(resAtten*4.)/4.]*len(freqs))
    data = np.asarray([resIDs, freqs, attens]).T
    np.savetxt(outputFN, data, fmt="%4i %10.1f %4i")

def makeRandomFreqSideband(startFreq, endFreq, nChannels, toneBandwidth, freqResolution):
    if nChannels <1:
        return np.asarray([],dtype=np.int)
    #if nChannels==1:
    #    return np.asarray([startFreq])
    avgSpacing = (endFreq - startFreq)/nChannels
    freqs = np.linspace(startFreq, endFreq, nChannels, False)+avgSpacing/2.
    freqs+= np.random.rand(len(freqs)) * avgSpacing - avgSpacing/2.
    
    #Correct doubles
    for arg in range(len(freqs)-1):
        if (freqs[arg+1] - freqs[arg]) <toneBandwidth:
            if arg==0: f_low =startFreq - toneBandwidth + freqResolution
            else: f_low = freqs[arg -1]
            if arg>=(len(freqs)-2): f_high = endFreq + toneBandwidth - freqResolution
            else: f_high = freqs[arg+2]
            
            f_spacing = (f_high - f_low) / 3.0
            if f_spacing>=toneBandwidth:       #push the two tones between f_high and f_low
                freqs[arg]=f_low+f_spacing
                freqs[arg+1]=f_low+2.0*f_spacing
            elif (f_high - f_low) /2.0 >= toneBandwidth:   #push one tone halfway between f_high and f_low
                freqs[arg]=(f_high - f_low)/2.0
                freqs[arg+1] = freqs[arg]
            else:                                       #remove both tones
                freqs[arg] = f_low
                freqs[arg+1]=f_low
    freqs=np.unique(freqs)  #sort and remove duplicates
    
    return freqs


def takeMultPowerSweeps(roachNums, startFreqs=None, endFreqs=None, startDacAtten=1, endDacAtten=None, attenStep=1., loStepQ=1, nOverlap=10, freqList='rfFreqs.txt', defineLUTs=False, outputFN='psData.npz'):
    """
    calls takePowerSweep() in different threads so that multiple roaches freq sweep simultaneously

    Inputs are the same as takePowerSweep() except roachNums, startFreqs, and endFreqs are lists

    There is no return value. The data is forcibly saved to disk
    """
    if startFreqs is None or endFreqs is None:
        startFreqs=np.asarray([3.5E9]*len(roachNums))
        startFreqs[1::2]+=2.5E9
        endFreqs=np.asarray([6.E9]*len(roachNums))
        endFreqs[1::2]+=2.5E9
    if outputFN is None: outputFN='psData.npz'
    threads = []
    for i, rNum in enumerate(roachNums):
        t=threading.Thread(target=takePowerSweep, args=(rNum,startFreqs[i],endFreqs[i],startDacAtten, endDacAtten, attenStep, loStepQ, nOverlap, freqList, defineLUTs, outputFN,))
        threads.append(t)
        t.start()
    for t in threads:
        t.join()

    #threads=[]
    #for i in range(len(roachNums)):
    #    pe=Pool(1)
    #    pe.apply_async(takePowerSweep, (roachNums[i],startFreqs[i],endFreqs[i],startDacAtten, endDacAtten, attenStep, loStepQ, nOverlap, freqList, defineLUTs, outputFN,))
    #    threads.append(pe)
    #for p in threads:
    #    p.close()
    #for p in threads:
    #    p.join()
    


def takePowerSweep(rNum, startFreq=3.5E9, endFreq=6.E9, startDacAtten=1, endDacAtten=None, attenStep=1., loStepQ=1, nOverlap=10, freqList='rfFreqs.txt', defineLUTs=False, outputFN='psData.npz'):
    """
    Do a power sweep!

    INPUTS:
        rNum - roach Number
        startFreq - [Hz]
        endFreq - [Hz] freq range inclusive
        startDacAtten - [dB]
        endDacAtten - [dB] attenuation values inclusive
        attenStep - [dB]
        loStepQ - LO step size quantized by dac freq resolution. So loStepQ=2 means step the LO by 2 dac freq resolution elements
        nOverlap - The number of overlapping points for tones. 
        freqList - passed on to setupRoach4FreqSweep()
        defineLUTs - passed on to setupRoach4FreqSweep()
        outputFN - if not None, passed on to FreqSweep.savePowerSweep(). "_rNum" is added automatically to the name

    OUTPUTS:
        I_vals - [ADC units] 3d array with dimensions [nAttens, nTones, nLOsteps]. 
        Q_vals - 
        freqList - [Hz] 2d array with dimensions [nTones, nLOsteps].
        attens - [dB] 1d array with dimensions [nAtten]. This is the absolute attenuation for each tone
    """
    roachController = setupRoach4FreqSweep(rNum, freqFN=freqList, defineLUTs=defineLUTs)
    try:
        if roachController is None: raise TypeError
        if startDacAtten==None: startDacAtten=roachController.globalDacAtten
        if endDacAtten==None: endDacAtten=startDacAtten
        resAtten=roachController.attenList[0]
        attenList = np.arange(startDacAtten, endDacAtten+attenStep, attenStep)  #The list of dacAttenuation values to loop through

        loStepQ=max(int(loStepQ),1)
        nOverlap=max(int(nOverlap),1)
        dacFreqResolution = roachController.params['dacSampleRate']/(roachController.params['nDacSamplesPerCycle']*roachController.params['nLutRowsToUse'])
        dacQuantizedFreqList = roachController.dacQuantizedFreqList
        dacQuantizedFreqList[np.where(dacQuantizedFreqList>(roachController.params['dacSampleRate']/2.))] -= roachController.params['dacSampleRate']
        freqSpan = np.abs(endFreq - startFreq)                          #The total span we want data for
        loStep = dacFreqResolution*loStepQ                              #LO step size in Hz
        try: loSpan = np.amax(np.diff(dacQuantizedFreqList))            #lo span for single sweep in Hz (freqlist is ordered so loSpan>0)
        except ValueError: loSpan=freqSpan                              #If there's only 1 tone in freq list
        toneSpan_low = np.amin(dacQuantizedFreqList)                    #Span of tone list below LO
        toneSpan_high = np.amax(dacQuantizedFreqList)                   #Span of tone list above LO
        toneSpan = toneSpan_high - toneSpan_low                         #Total span of tone list
        overlap = nOverlap*loStepQ*dacFreqResolution                    #The tones actually need to overlap a bit at the edges
        nSweeps = int(np.ceil((freqSpan-overlap)/(loSpan+toneSpan)))           #Number of sweeps to cover total span
        if toneSpan>0: loSpan+=overlap                                  #We'll run the LO a little bit more to overlap neighboring tones
        sweepSpan=toneSpan+loSpan                                       #Total span of a single sweep
        if sweepSpan>freqSpan:                                          #This shouldn't happen but we'll handle it if it does
            loSpan=freqSpan                                             #The tones won't overlap in this case...
            Warnings.warn("Either your DAC tones are too far apart or you're looking at a very small freq range")
        
        #print '\nSweep Details:'
        #print freqSpan/10.**6.
        #print loStep/10.**6.
        #print loSpan/10.**6.
        #print toneSpan/10.**6.
        #print overlap/10.**6.
        #print sweepSpan/10.**6.
        #print toneSpan_low/10.**6.
        #print toneSpan_high/10.**6.
        #print nSweeps
        #print ''

        
        #Now start powersweeping!
        newADCAtten=30. #Arbitrary first guess
        I_vals = []
        Q_vals=[]
        for i, dacAtten in enumerate(attenList):
            dacAtten1 = np.floor(dacAtten*2)/4.
            dacAtten2 = np.ceil(dacAtten*2)/4.
            roachController.changeAtten(1,dacAtten1)
            roachController.changeAtten(2,dacAtten2)
            newADCAtten = roachController.getOptimalADCAtten(newADCAtten)
            print "Roach "+str(rNum)+": "+str(i+1)+' of '+str(len(attenList))+' dacAttens'

            I_list = []
            Q_list = []
            freq_list = []
            for j in range(nSweeps):
                #loStart = startFreq + (endFreq-startFreq)*(j+1.)/(nSweeps+1.) - sweepSpan/2. - toneSpan_low
                loStart = min(endFreq,startFreq) - toneSpan_low
                if j>0: loStart+= 1.0*j/(nSweeps -1.)*(freqSpan - sweepSpan)
                roachController.setLOFreq(loStart)
                loEnd = loStart+loSpan
                iqData = roachController.performIQSweep(loStart/1.e6, loEnd/1.e6, loStep/1.e6)
                #iqData = roachController.performIQSweep(loStart/1.e6, (loStart+5*loStep)/1.e6, loStep/1.e6)
                I_list.append(iqData['I'])
                Q_list.append(iqData['Q'])
                freq_list.append( np.repeat([dacQuantizedFreqList+loStart],len(iqData['freqOffsets']),0).T + 
                                  np.repeat([iqData['freqOffsets']], len(dacQuantizedFreqList),0))
                
            I_list = np.reshape(I_list, (nSweeps*len(dacQuantizedFreqList), -1))
            Q_list = np.reshape(Q_list, (nSweeps*len(dacQuantizedFreqList), -1))
            I_vals.append(I_list)
            Q_vals.append(Q_list)

        I_vals = np.reshape(I_vals, (len(attenList), nSweeps*len(dacQuantizedFreqList), -1))
        Q_vals = np.reshape(Q_vals, (len(attenList), nSweeps*len(dacQuantizedFreqList), -1))
        freq_list = np.reshape(freq_list, (nSweeps*len(dacQuantizedFreqList), -1))
        attens = attenList - roachController.globalDacAtten + resAtten

        #Put attenuators back to normal
        dacAtten1 = np.floor(roachController.globalDacAtten*2)/4.
        dacAtten2 = np.ceil(roachController.globalDacAtten*2)/4.
        roachController.changeAtten(1,dacAtten1)
        roachController.changeAtten(2,dacAtten2)
        roachController.getOptimalADCAtten(newADCAtten)

        #Save and finish
        if outputFN is not None:
            outputFN = outputFN.rsplit('.npz',1)[0]+'_'+str(rNum)+'.npz'
            FreqSweep.savePowerSweep(outputFN, I_vals, Q_vals, freq_list, attens)
        return I_vals, Q_vals, freq_list, attens
    except:
        exc_info=sys.exc_info()
        print str(rNum)+" ERROR"
        traceback.print_exception(*exc_info)
        del exc_info
        return None

def plotWS(fn,roachNums):

    colors=['blue', 'darkblue', 'red', 'darkred', 'lime', 'green', 'violet', 'purple', 'cyan', 'teal', 'yellow', 'olive','silver', 'dimgrey']
    
    plt.figure()
    for i, rNum in enumerate(roachNums):
        #fn= widesweepFN+str(rNum)+'.txt'
        filename=fn+'_'+str(rNum)+'.npz'
        
        data=np.load(filename)
        I = data['I'][0].flatten()
        Q = data['Q'][0].flatten()
        freqs = data['freqs'].flatten()
        s21 = np.log10(I**2. + Q**2.)

        plt.plot(freqs, s21, ls='-',c=colors[i], label=str(rNum))

    plt.xlabel('Freq [GHz]')
    plt.ylabel('Power')
    plt.legend()
    plt.show()

class FreqSweep:

    @staticmethod
    def savePowerSweep(fn, I_vals, Q_vals, freqList, attens):
        np.savez(fn, I=I_vals, Q=Q_vals, freqs=freqList, atten=attens)

    def loadPowerSweep(self,fn):
        self.data=np.load(fn)
        print self.data
        print 
    
    def plotTransmissionData(self):
        plt.figure()
        for i, atten in enumerate(self.data['atten']):
            for j, tones in enumerate(self.data['freqs']):
                s21 = np.log10(self.data['I'][i, j,:]**2. + self.data['Q'][i, j,:]**2.)
                freqs = self.data['freqs'][j]/10.**9.
                
                plt.plot(freqs,s21,ls='-')
        plt.xlabel('Freq [GHz]')
        plt.ylabel('Power')
        plt.show()




if __name__ == "__main__":
    
    #generateWidesweepFreqList('/home/mecvnc/MKIDReadout/mkidreadout/channelizer/darknessfpga.param')

    args = sys.argv[1:]
    rNums = np.atleast_1d(args).astype(dtype=np.int)
    #setupMultRoaches4FreqSweep(rNums, defineLUTs=True)


    #setupRoach4FreqSweep(220,defineLUTs=True)

    

    #takePowerSweep(220, startFreq=3.5E9, endFreq=6.E9, startDacAtten=6, endDacAtten=6, attenStep=1., loStepQ=1, nOverlap=10, freqList='rfFreqs.txt', defineLUTs=False, outputFN='psData.npz')

    #takeMultPowerSweeps(rNums,startFreqs=None, endFreqs=None, startDacAtten=6, endDacAtten=6, attenStep=1., loStepQ=1, nOverlap=10, freqList='rfFreqs.txt', defineLUTs=False, outputFN='psData.npz')

    #f=FreqSweep()
    #f.loadPowerSweep('psData_220.npz')
    #f.plotTransmissionData()

    #f.loadPowerSweep('psData_220.npz')
    #f.plotTransmissionData()


    plotWS('psData',rNums)




