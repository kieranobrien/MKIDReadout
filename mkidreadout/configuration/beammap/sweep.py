"""
Author: Alex Walter
Date: June 5, 2018

This file contains classes and functions used to create a rough beammap
A rough beammap is the following format:
resID   flag    time_x  time_y
[int    int     float   float]

A regular beammap is:
resID   flag    loc_x   loc_y
[int    int     int     int]


Classes in this file:
BeamSweep1D(imageList, pixelComputationMask=None, minCounts=5, maxCountRate=2499)
ManualRoughBeammap(x_images, y_images, initialBeammap, roughBeammapFN)
RoughBeammap(configFN)
BeamSweepGaussFit(imageList, initialGuessImage)

Usage:
    From the commandline:
    $ python sweep.py sweep.cfg [-cc]

    The optional -cc option will run the crosscorellation and create a new rough beammap
    Otherwise, it will run the manual click GUI

"""

import os

import matplotlib
import numpy as np

matplotlib.use('Qt4Agg')
import matplotlib.pyplot as plt
from mkidcore.config import importoldconfig, ConfigThing, _consolidateconfig
from mkidcore.corelog import getLogger, create_log

import argparse

from mkidreadout.configuration.beammap.utils import crossCorrelateTimestreams, determineSelfconsistentPixelLocs2, \
    loadImgFiles, minimizePixelLocationVariance, snapToPeak, shapeBeammapIntoImages, fitPeak, getPeakCoM, check_timestream
from mkidreadout.configuration.beammap.flags import beamMapFlags


class FitBeamSweep(object):
    """
    Uses a fit to find peak in lightcurve (currently either gaussian or CoM)
    Can be used to refine the output of the cross-correlation.

    
    """

    def __init__(self, imageList, locEstimates=None):
        self.imageList = imageList
        self.initialGuessImage = locEstimates
        self.peakLocs = np.empty(imageList[0].shape)
        self.peakLocs[:] = np.nan

    def fitRoughPeakLocs(self, fitType, fitWindow=20):
        """
        INPUTS:
            fitWindow - Only find peaks within this window of the initial guess

        Returns:
            peakLocs - map of peak locations for each pixel
        """
        fitType = fitType.lower()
        if fitType!='gaussian' and fitType!= 'com':
            raise Exception('fitType must be either Gaussian or CoM!')
        for y in range(self.imageList[0].shape[0]):
            for x in range(self.imageList[0].shape[1]):
                timestream = self.imageList[:, y, x]
                if self.initialGuessImage is None or np.logical_not(np.isfinite(self.initialGuessImage[y, x])):
                    peakGuess=np.nan
                else:
                    peakGuess=self.initialGuessImage[y, x]

                if fitType == 'gaussian':
                    self.peakLocs[y,x] = fitPeak(timestream, peakGuess, fitWindow)[0]
                elif fitType == 'com':
                    self.peakLocs[y,x] = getPeakCoM(timestream, peakGuess, fitWindow)
        return self.peakLocs


class CorrelateBeamSweep(object):
    """
    This class is for computing a rough beammap using a list of images
    
    It uses a complicated cross-correlation function to find the pixel locations
    """

    def __init__(self, imageList, pixelComputationMask=None, minCounts=5, maxCountRate=2499):
        """
        Be careful, this function doesn't care about the units of time in the imageList
        The default minCounts, maxCountRate work well when the images are binned as 1 second exposures        

        INPUTS:
            imageList - list of images
            pixelComputationMask - It takes too much memory to calculate the beammap for the whole array at once. 
                                   This is a 2D array of integers (same shape as an image) with the value at each pixel 
                                   that corresponds to the group we want to compute it with.
            minCounts - integer of minimum counts during total exposure for it to be a good pixel
            maxCountRate - Check that the countrate is less than this in every image frame
        """
        self.imageList = np.asarray(imageList)

        # Use these parameters to determine what's a good pixel
        self.minCounts = minCounts  # counts during total exposure
        self.maxCountRate = maxCountRate  # counts per image frame

        nPix = np.prod(self.imageList[0].shape)
        nTime = len(self.imageList)
        bkgndList = 1.0 * np.median(self.imageList, axis=0)
        nCountsList = 1.0 * np.sum(self.imageList, axis=0)
        maxCountsList = 1.0 * np.amax(self.imageList, axis=0)
        badPix = np.where(np.logical_not(
            (nCountsList > minCounts) * (maxCountsList < maxCountRate) * (bkgndList < nCountsList / nTime)))

        if pixelComputationMask is None:
            nGoodPix = nPix - len(badPix[0])
            # nGroups=np.prod(imageList.shape)*(np.prod(imageList[0].shape)-1)/(200*3000*2999)*nGoodPix/nPix     # 300 timesteps x 3000 pixels takes a lot of memory...
            nGroups = nTime * nGoodPix * (nGoodPix - 1) / (600 * 3000 * 2999.)
            nGroups = nGoodPix / 1200.
            nGroups = max(nGroups, 1.)
            pixelComputationMask = np.random.randint(0, int(round(nGroups)), imageList[0].shape)
            # pixelComputationMask=np.repeat(range(5),2000).reshape(imageList[0].shape)
        self.compMask = np.asarray(pixelComputationMask)
        if len(badPix[0]) > 0:
            self.compMask[badPix] = np.amax(self.compMask) + 1  # remove bad pixels from the computation
            self.compGroups = (np.unique(self.compMask))[:-1]
        else:
            self.compGroups = np.unique(self.compMask)

    def getAbsOffset(self, shiftedTimes, auto=True, locLimit=None):
        """
        The autocorrelation function can only calculate relative time differences
        between pixels. This function defines the absolute time reference (ie. the
        location of the peak)

        INPUTS:
            shiftedTimes: a list of pixel time streams shifted to match up
            auto: if False then ask user to click on a plot
        """
        if not np.isfinite(locLimit) or locLimit<0 or locLimit>=len(shiftedTimes): locLimit=-1
        offset = np.argmax(np.sum(shiftedTimes[:locLimit], axis=0))
        if auto: return offset

        getLogger('beammap').info("Please click the correct peak")
        fig, ax = plt.subplots()
        for p_i in range(len(shiftedTimes)):
            ax.plot(shiftedTimes[p_i])
        ax.plot(np.sum(shiftedTimes, axis=0), 'k-')
        ln = ax.axvline(offset, c='b')

        def onclick(event):
            if fig.canvas.manager.toolbar._active is None:
                offset = event.xdata
                getLogger('beammap').info(offset)
                ln.set_xdata(offset)
                plt.draw()

        cid = fig.canvas.mpl_connect('button_press_event', onclick)
        plt.show()
        return offset

    def findRelativePixelLocations(self, locLimit=None):
        """
        Use auto correllation and least squares to find best time offsets between pixels
        """
        try:
            locs = np.empty(self.imageList[0].shape)
        except TypeError:
            return []
        locs[:] = np.nan

        for g in self.compGroups:
            # for g in [0]:
            getLogger('beammap').info('Starting group {}'.format(g))
            compPixels = np.where(self.compMask == g)

            timestreams = np.transpose(self.imageList[:, compPixels[0], compPixels[1]])  # shape [nPix, nTime]
            correlationList, goodPix = crossCorrelateTimestreams(timestreams, self.minCounts, self.maxCountRate)
            if len(goodPix) == 0: continue
            correlationLocs = np.argmax(correlationList, axis=1)

            correlationQaulity = 1.0 * np.amax(correlationList, axis=1) / np.sum(correlationList, axis=1)
            # correlationQuality = np.sum((correlationList[:,:len(goodPix)/2] - (correlationList[:,-1:-len(goodPix)/2-1:-1]))**2.,axis=1)     #subtract the mirror, square, and sum. If symmetric then it should be near 0
            # pdb.set_trace()
            del correlationList

            getLogger('beammap').info("Making Correlation matrix...")
            corrMatrix = np.zeros((len(goodPix), len(goodPix)))
            corrMatrix[np.triu_indices(len(goodPix), 1)] = correlationLocs - len(self.imageList) / 2
            corrMatrix[np.tril_indices(len(goodPix), -1)] = -1 * np.transpose(corrMatrix)[
                np.tril_indices(len(goodPix), -1)]
            del correlationLocs
            corrQualityMatrix = np.ones((len(goodPix), len(goodPix)))
            corrQualityMatrix[np.triu_indices(len(goodPix), 1)] = correlationQaulity
            corrQualityMatrix[np.tril_indices(len(goodPix), -1)] = -1 * np.transpose(corrQualityMatrix)[
                np.tril_indices(len(goodPix), -1)]
            del correlationQaulity
            getLogger('beammap').info("Done...")

            getLogger('beammap').info("Finding Best Relative Locations...")
            a = minimizePixelLocationVariance(corrMatrix)
            bestPixelArgs, totalVar = determineSelfconsistentPixelLocs2(corrMatrix, a)
            bestPixels = goodPix[bestPixelArgs]
            bestPixels = bestPixels[: len(bestPixels) / 20]
            best_a = minimizePixelLocationVariance(corrMatrix[:, np.where(np.in1d(goodPix, bestPixels))[0]])
            getLogger('beammap').info("Done...")

            getLogger('beammap').info("Finding Timestream Peak Locations...")
            shifts = np.rint(best_a[bestPixelArgs]).astype(np.int)
            shifts = shifts[: len(bestPixels)]
            shifts = shifts[:, None] + np.arange(len(timestreams[0]))
            shifts[np.where(shifts < 0)] = -1
            shifts[np.where(shifts >= len(timestreams[0]))] = -1
            bkgndList = 1.0 * np.median(timestreams[bestPixels], axis=1)
            nCountsList = 1.0 * np.sum(timestreams[bestPixels], axis=1)
            shiftedTimes = np.zeros((len(bestPixels), len(timestreams[0]) + 1))
            shiftedTimes[:, :-1] = (timestreams[bestPixels] - bkgndList[:, None]) / nCountsList[:,
                                                                                    None]  # padded timestream with 0
            shiftedTimes = shiftedTimes[np.arange(len(bestPixels))[:, None], shifts]  # shift each timestream
            # offset = np.argmax(np.sum(shiftedTimes,axis=0))
            offset = self.getAbsOffset(shiftedTimes, locLimit=locLimit)
            del shiftedTimes

            best_a += offset

            getLogger('beammap').info("Done...")

            locs[compPixels[0][goodPix], compPixels[1][goodPix]] = best_a

        locs[np.where(locs < 0)] = 0
        locs[np.where(locs >= len(self.imageList))] = len(self.imageList)
        return locs


class ManualRoughBeammap(object):
    def __init__(self, x_images, y_images, initialBeammap, roughBeammapFN, fitType = None):
        """
        Class for manually clicking through beammap.
        Saves a rough beammap with filename roughBeammapFN-HHMMSS.txt
        A 'rough' beammap is one that doesn't have x/y but instead the peak location in time from the swept light beam.

        INPUTS:
            x_images - list of images for sweep(s) in x-direction
            y_images -
            initialBeammap - path+filename of initial beammap used for making the images
            roughBeammapFN - path+filename of the rough beammap (time at peak instead of x/y value)
                             If the roughBeammap doesn't exist then it will be instantiated with nans
                             We append a timestamp to this string as the output file
            fitType - Type of fit to use when finding exact peak location from click. Current options are
                             com and gaussian. Ignored if None (default).
        """
        self.x_images = x_images
        self.y_images = y_images
        totalCounts_x = np.sum(self.x_images, axis=0)
        totalCounts_y = np.sum(self.y_images, axis=0)
        self.nTime_x = len(self.x_images)
        self.nTime_y = len(self.y_images)

        self.initialBeammapFN = initialBeammap
        self.roughBeammapFN = roughBeammapFN
        # self.outputBeammapFn = roughBeammapFN.rsplit('.',1)[0]+time.strftime('-%H%M%S')+'.txt'
        self.outputBeammapFn = roughBeammapFN.rsplit('.', 1)[0] + '_clicked.bmap'
        if os.path.isfile(self.outputBeammapFn):
            self.roughBeammapFN = self.outputBeammapFn
        self.resIDsMap, self.flagMap, self.x_loc, self.y_loc = shapeBeammapIntoImages(self.initialBeammapFN,
                                                                                      self.roughBeammapFN)
        if self.roughBeammapFN is None or not os.path.isfile(self.roughBeammapFN):
            self.flagMap[np.where(self.flagMap != beamMapFlags['noDacTone'])] = beamMapFlags['failed']

        self.fitType = fitType.lower()

        ##Snap to peak
        # for row in range(len(self.x_loc)):
        #    for col in range(len(self.x_loc[0])):
        #        self.x_loc[row, col] = snapToPeak(self.x_images[:,row,col],self.x_loc[row,col],10)
        # for row in range(len(self.y_loc)):
        #    for col in range(len(self.y_loc[0])):
        #        self.y_loc[row, col] = snapToPeak(self.y_images[:,row,col],self.y_loc[row,col],10)
        # self.saveRoughBeammap()

        self.goodPix = np.where((self.flagMap != beamMapFlags['noDacTone']) * (totalCounts_x + totalCounts_y) > 0)
        self.nGoodPix = len(self.goodPix[0])
        getLogger('beammap').info('Pixels with light: {}'.format(self.nGoodPix))
        self.curPixInd = 0
        self.curPixValue = np.amax(beamMapFlags.values()) + 1

        self._want_to_close = False
        self.plotFlagMap()
        self.plotXYscatter()
        self.plotTimestream()

        plt.show()

    def saveRoughBeammap(self):
        getLogger('beammap').info('Saving: '.format(self.outputBeammapFn))
        allResIDs = self.resIDsMap.flatten()
        flags = self.flagMap.flatten()
        x = self.x_loc.flatten()
        y = self.y_loc.flatten()
        args = np.argsort(allResIDs)
        data = np.asarray([allResIDs[args], flags[args], x[args], y[args]]).T
        np.savetxt(self.outputBeammapFn, data, fmt='%7d %3d %7f %7f')

    def plotTimestream(self):
        self.fig_time, (self.ax_time_x, self.ax_time_y) = plt.subplots(2)
        y = self.goodPix[0][self.curPixInd]
        x = self.goodPix[1][self.curPixInd]

        xStream = self.x_images[:, y, x]
        ln_xStream, = self.ax_time_x.plot(xStream)
        x_loc = self.x_loc[y, x]
        if np.logical_not(np.isfinite(x_loc)): x_loc = -1
        ln_xLoc = self.ax_time_x.axvline(x_loc, c='r')

        yStream = self.y_images[:, y, x]
        ln_yStream, = self.ax_time_y.plot(yStream)
        y_loc = self.y_loc[y, x]
        if np.logical_not(np.isfinite(y_loc)): y_loc = -1
        ln_yLoc = self.ax_time_y.axvline(y_loc, c='r')

        # self.ax_time_x.set_title('Pix '+str(self.curPixInd)+' resID'+str(int(self.resIDsMap[y,x]))+' ('+str(x)+', '+str(y)+')')
        flagStr = [key for key, value in beamMapFlags.items() if value == self.flagMap[y, x]][0]
        self.ax_time_x.set_title(
            'Pix ' + str(self.curPixInd) + '; resID' + str(int(self.resIDsMap[y, x])) + '; (' + str(x) + ', ' + str(
                y) + '); flag ' + str(flagStr))
        self.ax_time_x.set_ylabel('X counts')
        self.ax_time_y.set_ylabel('Y counts')
        self.ax_time_y.set_xlabel('Timesteps')
        self.ax_time_x.set_xlim(-2, self.nTime_x + 2)
        self.ax_time_y.set_xlim(-2, self.nTime_y + 2)
        self.ax_time_x.set_ylim(0, None)
        self.ax_time_y.set_ylim(0, None)

        self.timestreamPlots = [ln_xLoc, ln_yLoc, ln_xStream, ln_yStream]

        self.fig_time.canvas.mpl_connect('button_press_event', self.onClickTime)
        self.fig_time.canvas.mpl_connect('close_event', self.onCloseTime)
        self.fig_time.canvas.mpl_connect('key_press_event', self.onKeyTime)

    def onKeyTime(self, event):
        getLogger('beammap').info('Pressed '+event.key)
        # if event.key not in ('right', 'left'): return
        if event.key in ['right', 'c']:
            self.curPixInd += 1
            self.curPixInd %= self.nGoodPix
            self.updateTimestreamPlot()
            self.updateXYPlot(1)
            self.updateFlagMapPlot()
        elif event.key in [' ']:
            self.curPixInd += 1
            self.curPixInd %= self.nGoodPix
            self.updateTimestreamPlot(fastforward=True)
            self.updateXYPlot(1)
            self.updateFlagMapPlot()
        elif event.key in ['r']:
            self.curPixInd -= 1
            self.curPixInd %= self.nGoodPix
            self.updateTimestreamPlot(rewind=True)
            self.updateXYPlot(1)
            self.updateFlagMapPlot()
        elif event.key in ['left']:
            self.curPixInd -= 1
            self.curPixInd %= self.nGoodPix
            self.updateTimestreamPlot()
            self.updateXYPlot(1)
            self.updateFlagMapPlot()
        elif event.key in ['b']:
            y = self.goodPix[0][self.curPixInd]
            x = self.goodPix[1][self.curPixInd]
            self.x_loc[y, x] = np.nan
            self.y_loc[y, x] = np.nan
            getLogger('beammap').info('Pix {} ({}, {}) Marked bad'.format(int(self.resIDsMap[y, x]),x,y))
            self.updateFlagMap(self.curPixInd)
            self.curPixInd += 1
            self.curPixInd %= self.nGoodPix
            self.updateTimestreamPlot()
            self.updateXYPlot(2)
            self.updateFlagMapPlot()
        elif event.key in ['d']:
            y = self.goodPix[0][self.curPixInd]
            x = self.goodPix[1][self.curPixInd]
            if self.flagMap[y, x] != beamMapFlags['double']:
                self.flagMap[y, x] = beamMapFlags['double']
                getLogger('beammap').info('Pix {} ({}, {}) Marked as double'.format(int(self.resIDsMap[y, x]), x, y))
            else:
                self.flagMap[y, x] = beamMapFlags['good']
                getLogger('beammap').info('Pix {} ({}, {}) Un-Marked as double'.format(int(self.resIDsMap[y, x]), x, y))
            self.updateFlagMap(self.curPixInd)
            self.updateTimestreamPlot(5)

    def onCloseTime(self, event):
        if not self._want_to_close:
            self.curPixInd += 1
            self.curPixInd %= self.nGoodPix
            self.updateTimestreamPlot()
            self.plotTimestream()
            plt.show()
        # event.ignore()
        # self.fig_time.show()

    def updateTimestreamPlot(self, lineNum=4, fastforward = False, rewind = False):
        y = self.goodPix[0][self.curPixInd]
        x = self.goodPix[1][self.curPixInd]

        if fastforward or rewind:
            skip_timestream = True
            counter = 0
            while skip_timestream and counter < self.nGoodPix:
                counter += 1
                y = self.goodPix[0][self.curPixInd]
                x = self.goodPix[1][self.curPixInd]
                xStream = self.x_images[:, y, x]
                yStream = self.y_images[:, y, x]
                y_loc = self.y_loc[y, x]
                x_loc = self.x_loc[y, x]
                xStream_good = check_timestream(xStream, x_loc)
                if not xStream_good:
                    print('x failed check')
                yStream_good = check_timestream(yStream, y_loc)
                if not yStream_good:
                    print('y failed check')
                skip_timestream = xStream_good and yStream_good
                if skip_timestream:
                    if fastforward:
                        self.curPixInd += 1
                    else:
                        self.curPixInd -= 1
                    self.curPixInd %= self.nGoodPix

        if lineNum == 0 or lineNum >= 4:
            offset = self.x_loc[y, x]
            if np.logical_not(np.isfinite(offset)): offset = -1
            self.timestreamPlots[0].set_xdata(offset)
        if lineNum == 1 or lineNum >= 4:
            offset = self.y_loc[y, x]
            if np.logical_not(np.isfinite(offset)): offset = -1
            self.timestreamPlots[1].set_xdata(offset)
        if lineNum == 2 or lineNum >= 4:
            self.timestreamPlots[2].set_ydata(self.x_images[:, y, x])
            # self.ax_time_x.autoscale(True,'y',True)
            self.ax_time_x.set_ylim(0, 1.05 * np.amax(self.x_images[:, y, x]))
            self.ax_time_x.set_xlim(-2, self.nTime_x + 2)
        if lineNum == 3 or lineNum >= 4:
            self.timestreamPlots[3].set_ydata(self.y_images[:, y, x])
            # self.ax_time_y.autoscale(True,'y',True)
            self.ax_time_y.set_ylim(0, 1.05 * np.amax(self.y_images[:, y, x]))
            self.ax_time_y.set_xlim(-2, self.nTime_y + 2)
        if lineNum == 2 or lineNum == 3 or lineNum == 4 or lineNum == 5:
            flagStr = [key for key, value in beamMapFlags.items() if value == self.flagMap[y, x]][0]
            self.ax_time_x.set_title(
                'Pix ' + str(self.curPixInd) + '; resID' + str(int(self.resIDsMap[y, x])) + '; (' + str(x) + ', ' + str(
                    y) + '); flag ' + str(flagStr))
        self.fig_time.canvas.draw()

    def onClickTime(self, event):
        if self.fig_time.canvas.manager.toolbar._active is None:
            # update time plot and x/y_loc
            y = self.goodPix[0][self.curPixInd]
            x = self.goodPix[1][self.curPixInd]
            offset = event.xdata
            if offset < 0: offset = np.nan

            if event.inaxes == self.ax_time_x:
                offset = snapToPeak(self.x_images[:, y, x], offset)
                if self.fitType == 'gaussian':
                    fitParams=fitPeak(self.x_images[:,y,x],offset,20)
                    offset=fitParams[0]
                    getLogger('beammap').info('Gaussian fit params: ' + str(fitParams))
                elif self.fitType == 'com':
                    offset=getPeakCoM(self.x_images[:,y,x],offset)
                    getLogger('beammap').info('Using CoM: ' + str(offset), 10)
                self.x_loc[y, x] = offset
                getLogger('beammap').info('x: {}'.format(offset))
                self.updateTimestreamPlot(0)

            elif event.inaxes == self.ax_time_y:
                offset = snapToPeak(self.y_images[:, y, x], offset)
                if self.fitType == 'gaussian':
                    fitParams=fitPeak(self.y_images[:,y,x],offset,20)
                    offset=fitParams[0]
                    getLogger('beammap').info('Gaussian fit params: ' + str(fitParams))
                elif self.fitType == 'com':
                    offset=getPeakCoM(self.y_images[:,y,x],offset, 10)
                    getLogger('beammap').info('Using CoM: ' + str(offset))
                self.y_loc[y, x] = offset
                getLogger('beammap').info('y: {}'.format(offset))
                self.updateTimestreamPlot(1)

            self.updateXYPlot(2)
            self.updateFlagMap(self.curPixInd)

    def updateXYPlot(self, lines):
        if lines == 0 or lines == 2:
            self.ln_XY.set_data(self.x_loc.flatten(), self.y_loc.flatten())
        if lines == 1 or lines == 2:
            y = self.goodPix[0][self.curPixInd]
            x = self.goodPix[1][self.curPixInd]
            self.ln_XYcur.set_data([self.x_loc[y, x]], [self.y_loc[y, x]])

        self.ax_XY.autoscale(True)
        self.fig_XY.canvas.draw()

    def updateFlagMap(self, curPixInd):
        y = self.goodPix[0][curPixInd]
        x = self.goodPix[1][curPixInd]
        if np.isfinite(self.x_loc[y, x]) * np.isfinite(self.y_loc[y, x]):
            if self.flagMap[y, x] != beamMapFlags['double']: self.flagMap[y, x] = beamMapFlags['good']
        elif np.logical_not(np.isfinite(self.x_loc[y, x])) * np.isfinite(self.y_loc[y, x]):
            self.flagMap[y, x] = beamMapFlags['xFailed']
        elif np.isfinite(self.x_loc[y, x]) * np.logical_not(np.isfinite(self.y_loc[y, x])):
            self.flagMap[y, x] = beamMapFlags['yFailed']
        elif np.logical_not(np.isfinite(self.x_loc[y, x])) * np.logical_not(np.isfinite(self.y_loc[y, x])):
            self.flagMap[y, x] = beamMapFlags['failed']
        self.saveRoughBeammap()
        self.updateFlagMapPlot()

    def updateFlagMapPlot(self):
        flagMap_masked = np.ma.masked_where(self.flagMap == beamMapFlags['noDacTone'], self.flagMap)
        flagMap_masked[self.goodPix[0][self.curPixInd], self.goodPix[1][self.curPixInd]] = self.curPixValue
        self.ln_flags.set_data(flagMap_masked)
        self.fig_flags.canvas.draw()

    def plotFlagMap(self):
        self.fig_flags, self.ax_flags = plt.subplots()
        flagMap_masked = np.ma.masked_where(self.flagMap == beamMapFlags['noDacTone'], self.flagMap)
        my_cmap = matplotlib.cm.get_cmap('YlOrRd')
        my_cmap.set_under('w')
        my_cmap.set_over('c')
        my_cmap.set_bad('k')

        flagMap_masked[self.goodPix[0][self.curPixInd], self.goodPix[1][self.curPixInd]] = self.curPixValue
        self.ln_flags = self.ax_flags.matshow(flagMap_masked, cmap=my_cmap, vmin=0.1,
                                              vmax=np.amax(beamMapFlags.values()) + .1)
        self.ax_flags.set_title('Flag map')
        # cbar = self.fig_flags.colorbar(flagMap_masked, extend='both', shrink=0.9, ax=self.ax_flags)
        self.fig_flags.canvas.mpl_connect('button_press_event', self.onClickFlagMap)
        self.fig_flags.canvas.mpl_connect('close_event', self.onCloseFlagMap)

    def onCloseFlagMap(self, event):
        # plt.close(self.fig_XY)
        # plt.close(self.fig_time)
        plt.show()
        self._want_to_close = True
        plt.close('all')

    def onClickFlagMap(self, event):
        if self.fig_flags.canvas.manager.toolbar._active is None and event.inaxes == self.ax_flags:
            x = int(np.floor(event.xdata + 0.5))
            y = int(np.floor(event.ydata + 0.5))
            nRows, nCols = self.x_images[0].shape
            if x >= 0 and x < nCols and y >= 0 and y < nRows:
                msg = 'Clicked Flag Map! [{}, {}] -> {} Flag: {}'
                getLogger('beammap').info(msg.format(x, y, self.resIDsMap[y, x], self.flagMap[y, x]))
                pixInd = np.where((self.goodPix[0] == y) * (self.goodPix[1] == x))[0]
                if len(pixInd) == 1:
                    self.curPixInd = pixInd[0]
                    self.updateFlagMapPlot()
                    self.updateXYPlot(1)
                    self.updateTimestreamPlot(4)
                    # plt.draw()
                else:
                    getLogger('beammap').info("No photons detected")

    def plotXYscatter(self):
        self.fig_XY, self.ax_XY = plt.subplots()
        self.ln_XY, = self.ax_XY.plot(self.x_loc.flatten(), self.y_loc.flatten(), 'b.')
        y = self.goodPix[0][self.curPixInd]
        x = self.goodPix[1][self.curPixInd]
        self.ln_XYcur, = self.ax_XY.plot([self.x_loc[y, x]], [self.y_loc[y, x]], 'go')
        self.ax_XY.set_title('Pixel Locations')
        self.fig_XY.canvas.mpl_connect('close_event', self.onCloseXY)

    def onCloseXY(self, event):
        # self.fig_XY.show()
        if not self._want_to_close:
            self.plotXYscatter()
            plt.show()


class RoughBeammap():
    def __init__(self, config):
        """
        This class is for finding the rough location of each pixel in units of timesteps
        INPUTS:
            configFN - config file listing the sweeps and properties
        """
        self.config = config
        self.x_locs = None
        self.y_locs = None
        self.x_images = None
        self.y_images = None

    def stackImages(self, sweepType, median=True):

        sweepType = sweepType.lower()
        if sweepType not in ('x','y'):
            raise ValueError('sweepType must be x or y')
        sweepList = None
        nTimes = 0
        nSweeps = 0
        for s in self.config.beammap.sweep.sweeps:
            if s.sweeptype in sweepType:
                nSweeps += 1.
                imList = self.loadSweepImgs(s)
                direction = -1 if s.sweepdirection is '-' else 1
                if sweepList is None:
                    sweepList = np.asarray([imList[::direction, :, :]])
                    nTimes = len(imList)
                else:
                    if len(imList) < nTimes:
                        pad = np.empty((nTimes - len(imList), len(imList[0]), len(imList[0][0])))
                        pad[:] = np.nan
                        imList = np.concatenate((imList[::direction, :, :], pad), 0)
                    elif len(imList) > nTimes:
                        pad = np.empty((len(sweepList), len(imList) - nTimes, len(imList[0]), len(imList[0][0])))
                        pad[:] = np.nan
                        sweepList = np.concatenate((sweepList, pad), 1)
                        imList = imList[::direction, :, :]
                    sweepList = np.concatenate((sweepList, imList[np.newaxis, :, :, :]), 0)

                    # nTimes = min(len(imList), nTimes)
                    # imageList=imageList[:nTimes] + (imList[::direction,:,:])[:nTimes]

        if median:
            images = np.nanmedian(sweepList, 0)
        else:
            images = np.nanmean(sweepList, 0)
        if sweepType == 'x':
            self.x_images = images
        else:
            self.y_images = images
        getLogger('sweep.RoughBeammap').info('Stacked {} {} sweeps', int(nSweeps), sweepType)
        return images

    def concatImages(self, sweepType, removeBkg=True):
        """
        This won't work well if the background level or QE of the pixel changes between sweeps...
        Should remove this first
        """
        sweepType = sweepType.lower()
        assert sweepType in ('x', 'y')
        imageList = None
        for s in self.config.beammap.sweep.sweeps:
            if s.sweeptype in sweepType:
                getLogger('beammap').info('loading: ' + str(s))
                imList = self.loadSweepImgs(s).astype(np.float)
                if removeBkg:
                    bkgndList = np.median(imList, axis=0)
                    imList -= bkgndList
                direction = -1 if s.sweepdirection == '-' else 1
                if imageList is None:
                    imageList = imList[::direction, :, :]
                else:
                    imageList = np.concatenate((imageList, imList[::direction, :, :]), axis=0)
        if sweepType == 'x':
            self.x_images = imageList
        else:
            self.y_images = imageList
        return imageList

    def findLocWithCrossCorrelation(self, sweepType, pixelComputationMask=None, snapToPeaks=True,
                                    correctMultiSweep=True):
        """
        This function estimates the location in time for the light peak in each pixel by cross-correlating the timestreams
        See CorrelateBeamSweep class

        Careful: We assume the sweep speed is always the same when looking at multiple sweeps!!!
        For now, we assume initial beammap is the same too.

        INPUTS:
            sweepType - either 'x', or 'y'
            pixelComputationMask - see CorrelateBeamSweep.__init__()
            snapToPeaks - If true, snap the cross-correlation to the biggest nearby peak
            correctMultiSweep - see self.cleanCrossCorrelationToWrongSweep()

        OUTPUTS:
            locs - map of locations for each pixel [units of time]
        """
        imageList = self.concatImages(sweepType)
        dur = [s.duration for s in self.config.beammap.sweep.sweeps if s.sweeptype in sweepType.lower()]
        # FLMap = getFLMap(self.config.beammap.sweep.initialbeammap)

        sweep = CorrelateBeamSweep(imageList, pixelComputationMask)
        locs = sweep.findRelativePixelLocations(locLimit=dur[0])
        if snapToPeaks:
            for row in range(len(locs)):
                for col in range(len(locs[0])):
                    locs[row, col] = snapToPeak(imageList[:, row, col], locs[row, col])
        if correctMultiSweep:
            locs = self.cleanCrossCorrelationToWrongSweep(sweepType, locs)
        if sweepType in ['x', 'X']:
            self.x_locs = locs
        else:
            self.y_locs = locs
        return locs

    def cleanCrossCorrelationToWrongSweep(self, sweepType, locs):
        """
        If you're doing a cross-correlation with multiple timestreams concatenated after one another
        there is a common failure mode where the max cross-correlation will be where the peak in the
        first sweep matches the peak in the second sweep.

        If the sweeps are matched up, this function will correct that systematic error. If the sweep start
        times aren't matched up then this won't work
        """
        dur = [s.duration for s in self.config.beammap.sweep.sweeps if s.sweeptype in sweepType.lower()]
        for i in range(len(dur) - 1):
            locs[np.where(locs > dur[i])] -= dur[i]
        return locs

    def refinePeakLocs(self, sweepType, fitType, locEstimates=None, fitWindow=20):
        """
        This function refines the peak locations given by locEstimates with either a gaussian
        fit or center of mass calculation. Can also be used as a standalone routine (set
        locEstimates to None), but currently doesn't work well in this mode.

        Careful: The sweep start times must be aligned such that the light peaks stack up.
        We assume the sweep speed is always the same when looking at multiple sweeps!!!
        For now, we assume initial beammap is the same too.

        INPUTS:
            sweepType - either 'x', or 'y'
            locEstimate - optional guesses for peak location. Should be 2D map of peak locations

        OUTPUTS:
            locs - map of locations for each pixel [units of time]
        """
        imageList = self.stackImages(sweepType)
        sweep = FitBeamSweep(imageList, locEstimates)
        if locEstimates is None: fitWindow = None
        locs = sweep.fitRoughPeakLocs(fitType, fitWindow=fitWindow)
        if sweepType in ['x', 'X']:
            self.x_locs = locs
        else:
            self.y_locs = locs
        return locs

    # def computeSweeps(self, sweepType, pixelComputationMask=None):
    #    """
    #    Careful: We assume the sweep speed is always the same!!!
    #    For now, we assume initial beammap is the same too.
    #    """
    #    imageList=self.concatImages(sweepType)
    #    sweep = CorrelateBeamSweep(imageList,pixelComputationMask)
    #    locs=sweep.findRelativePixelLocations()
    #    sweepFit = BeamSweepGaussFit(imageList, locs)
    #    locs = sweepFit.fitRoughPeakLocs()
    #
    #    if sweepType in ['x','X']: self.x_locs=locs
    #    else: self.y_locs=locs
    #    self.saveRoughBeammap()

    def saveRoughBeammap(self):

        getLogger('beammap').info('Saving')
        allResIDs_map, flag_map, x_map, y_map = shapeBeammapIntoImages(self.config.beammap.sweep.initialbeammap,
                                                                       self.config.beammap.sweep.roughbeammap)
        otherFlagArgs = np.where((flag_map != beamMapFlags['good']) * (flag_map != beamMapFlags['failed']) * (
                    flag_map != beamMapFlags['xFailed']) * (flag_map != beamMapFlags['yFailed']))
        otherFlags = flag_map[otherFlagArgs]
        if self.y_locs is not None and self.y_locs.shape == flag_map.shape:
            y_map = self.y_locs
            getLogger('beammap').info('added y')
        if self.x_locs is not None and self.x_locs.shape == flag_map.shape:
            x_map = self.x_locs
            getLogger('beammap').info('added x')

        flag_map[np.where(np.logical_not(np.isfinite(x_map)) * np.logical_not(np.isfinite(y_map)))] = beamMapFlags[
            'failed']
        flag_map[np.where(np.logical_not(np.isfinite(x_map)) * np.isfinite(y_map))] = beamMapFlags['xFailed']
        flag_map[np.where(np.logical_not(np.isfinite(y_map)) * np.isfinite(x_map))] = beamMapFlags['yFailed']
        flag_map[np.where(np.isfinite(x_map) * np.isfinite(y_map))] = beamMapFlags['good']
        flag_map[otherFlagArgs] = otherFlags

        allResIDs = allResIDs_map.flatten()
        flags = flag_map.flatten()
        x = x_map.flatten()
        y = y_map.flatten()
        args = np.argsort(allResIDs)
        data = np.asarray([allResIDs[args], flags[args], x[args], y[args]]).T
        np.savetxt(self.config.beammap.sweep.roughbeammap, data, fmt='%7d %3d %7f %7f')

    def loadRoughBeammap(self):
        allResIDs_map, flag_map, self.x_locs, self.y_locs = shapeBeammapIntoImages(self.config.beammap.sweep.initialbeammap, self.config.beammap.sweep.roughbeammap)

    def loadSweepImgs(self, s):
        path = self.config.beammap.sweep.imgfiledirectory
        startTime = s.starttime
        duration = s.duration
        if duration % 2 == 0:
            getLogger('beammap.sweep').warn("Having an even number of time steps"
                                            "can create off by 1 errors: subtracting one time step to "
                                            "make it odd")
            duration -= 1
        fnList = [path + str(startTime + i) + '.img' for i in range(duration)]
        nRows = s.numrows
        nCols = s.numcols
        return loadImgFiles(fnList, nRows, nCols)

    def manualSweepCleanup(self):
        m = ManualRoughBeammap(self.x_images, self.y_images, self.config.beammap.sweep.initialbeammap,
                               self.config.beammap.sweep.roughbeammap, self.config.beammap.sweep.fittype)

    def plotTimestream(self):
        pass

def registersettings(cfgObj):
    cfgObj.register('beammap.sweep.imgfiledirectory', '')
    cfgObj.register('beammap.sweep.initialbeammap', '')
    cfgObj.register('beammap.sweep.roughbeammap', '')
    cfgObj.register('detector.nrow', 146)
    cfgObj.register('detector.ncol', 140)

    c = ConfigThing()
    c.register('type','x', allowed=('x', 'y'))
    c.register('direction', '+', allowed=('+', '-'))
    c.register('speed', 3)
    c.register('duration', 500)
    c.register('start', 1527724450)
    cfgObj.register('beammap.sweep.sweeps', [c])



if __name__ == '__main__':
    #setup_logging()
    create_log('Sweep')
    create_log('mkidcore')
    create_log('mkidreadout')
    log = getLogger('Sweep')


    parser = argparse.ArgumentParser(description='MKID Beammap Analysis Utility')
    parser.add_argument('cfgfile', type=str, default='sweep.cfg',help='Configuration file for beammap sweeps')
    parser.add_argument('-cc', default=False, action='store_true', dest='use_cc', help='run in Xcor mode')
    args = parser.parse_args()

    thisconfig = ConfigThing()
    importoldconfig(thisconfig, args.cfgfile, namespace='beammap.sweep')
    _consolidateconfig(thisconfig.beammap.sweep)
    #registersettings()

    log.info('Starting rough beammap')
    b = RoughBeammap(thisconfig)

    if args.use_cc: #Cross correllation mode
        b.loadRoughBeammap()
        b.concatImages('x',False)
        b.concatImages('y',False)
        b.findLocWithCrossCorrelation('x')
        b.findLocWithCrossCorrelation('y')
        b.refinePeakLocs('x', b.config.beammap.sweep.fittype, b.x_locs, fitWindow=15)
        b.refinePeakLocs('y', b.config.beammap.sweep.fittype, b.y_locs, fitWindow=15)
        b.saveRoughBeammap()
    else:   #Manual mode
        log.info('Stack x and y')
        b.stackImages('x')
        b.stackImages('y')
        log.info('Cleanup')
        b.manualSweepCleanup()

