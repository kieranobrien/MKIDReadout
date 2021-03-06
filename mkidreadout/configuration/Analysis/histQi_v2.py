#!/usr/bin/python
import os

import numpy as np
from matplotlib import pyplot as plt

#Plots Histogram of f, Q, and Distance of f to nearest neighbor, Q vs f, Dist to neigh vs f and saves it to a pdf.  You need to change the filename and pdftitle (and possibly the text position in line 79

datapath = '/mnt/data0/Darkness/20170530'
filename= 'M1_WS_FL2-autofit.log'
pdftitle=os.path.join(datapath, 'Varuna-'+filename[:-11].replace('_','-')+'split-hists.pdf')
filepath = os.path.join(datapath,filename)
autofit=np.loadtxt(filepath)

Qs=1.e-3*autofit[:,2]
badFitsMask = Qs == 5. 
print np.sum(badFitsMask),' bad fits removed'
autofit = autofit[~badFitsMask]

freqs=autofit[:,1]
Qs=1.e-3*autofit[:,2]
Qc=1.e-3*autofit[:,3]
Qi=1.e-3*np.abs(autofit[:,4])

freqCutoff = 6.7
lowFreqInds = np.where(freqs<freqCutoff)
highFreqInds = np.where(freqs>=freqCutoff)

lowFreqs = freqs[lowFreqInds]
lowFreqQs = Qs[lowFreqInds]
lowFreqQc = Qc[lowFreqInds]
lowFreqQi = Qi[lowFreqInds]
highFreqs = freqs[highFreqInds]
highFreqQs = Qs[highFreqInds]
highFreqQc = Qc[highFreqInds]
highFreqQi = Qi[highFreqInds]

ds=[]
fs=[]
freq=sorted(freqs)
for i in xrange(1,len(freqs)-1):
	x=abs(freq[i]-freq[i+1])
	y=abs(freq[i]-freq[i-1])
	if x>=y:
		ds.append(y)
	else:
		ds.append(x)
	fs.append(freq[i])
ds=[x*1000 for x in ds]

mf=np.median(freqs)
sf=np.std(freqs)
mq=np.median(Qs)
sq=np.std(Qs)
mqi=np.median(Qi)
sqi=np.std(Qi)
md=np.median(ds)
sd=np.std(ds)
nres=len(freqs)

fig = plt.figure(figsize=(6,8))
plt.subplots_adjust(left = 0.1, right= 0.96, bottom= .07, top= .96, wspace=0.3, hspace=0.4)


ax=fig.add_subplot(321)
ax.hist(freqs,bins=200, color='k')
ax.set_xlabel('Frequency (GHz)\nmedian=%f, std=%f'%(mf,sf), size=8)
ax.set_ylabel('Number', size=8)
ax.set_title('Histogram of Frequency', size=9)
ax.tick_params(labelsize=8)

max_q = 80
ax2=fig.add_subplot(323)
ax2.hist(lowFreqQs, bins=25, range=(0,max_q),color='b', histtype='step', label='Low Freq')
ax2.hist(highFreqQs, bins=25, range=(0,max_q),color='r', histtype='step', label='High Freq')
ax2.set_xlabel('$Q (10^3)$\nmedian=%f, std=%f'%(mq,sq), size=8)
ax2.set_ylabel('Number', size=8)
ax2.set_title('Histogram of Q', size=9)
ax2.legend()
ax2.set_xlim(0,max_q)
ax2.tick_params(labelsize=8)

#ax3=fig.add_subplot(325)
#ax3.hist(ds, bins=100, color='k')
#ax3.set_xlabel('Distance to Nearest Neighbor (MHz)\nmedian=%f, std=%f'%(md,sd), size=8)
#ax3.set_ylabel('Number', size=8)
#ax3.set_title('Distance of f0 to Nearest Neighbor', size=9)
#ax3.set_xlim(0,6)
#ax3.tick_params(labelsize=8)

max_qi = 300
ax3=fig.add_subplot(325)
ax3.hist(lowFreqQi, bins=25, range=(0,max_qi), color='b', histtype='step', label='Low Freq')
ax3.hist(highFreqQi, bins=25, range=(0,max_qi), color='r', histtype='step', label='High Freq')
ax3.set_xlabel('$Q_i (10^3)$\nmedian=%f, std=%f'%(mqi,sqi), size=8)
ax3.set_ylabel('Number', size=8)
ax3.set_title('Histogram of $Q_i$', size=9)
ax3.legend()
ax3.set_xlim(0,max_qi)
ax3.tick_params(labelsize=8)

ax4=fig.add_subplot(322)
ax4.plot(freqs,Qs,'r,')
ax4.set_xlabel('Resonant Frequency (GHz)', size=8)
ax4.set_ylabel('Q(k)', size=8)
ax4.set_title('Q vs f0', size=9)
ax4.tick_params(labelsize=8)
ax4.set_ylim(0,300)

ax5=fig.add_subplot(324)
ax5.plot(fs,ds,'b,')
ax5.set_xlabel('Resonant Frequency (GHz)', size=8)
ax5.set_ylabel('Distance of f to Nearest Neighbor (MHz)', size=8)
ax5.set_title('Nearest Neighbor vs f0', size=9)
ax5.tick_params(labelsize=8)
ax5.set_ylim(0,20)

#ax5.text(2.8,-15,'file name=\n%s\nnumber of resonators = %d'%(filepath, nres), size=8.5)

ax6=fig.add_subplot(326)
ax6.plot(freqs,Qi,'r,')
ax6.set_xlabel('Resonant Frequency (GHz)', size=8)
ax6.set_ylabel('Qi(k)', size=8)
ax6.set_title('Qi vs f0', size=9)
ax6.tick_params(labelsize=8)
ax6.set_ylim(0,300)


fig.savefig(pdftitle)
plt.show()
plt.close()
