import numpy as np
import glob
import matplotlib.pyplot as plt
from astropy.stats import mad_std
import scipy.optimize as opt


class BeammapShifter(object):
    def __init__(self, designFL, rawMapFile, psFiles, instrument):
        self.instrument = instrument
        self.design = np.flipud(np.fliplr(np.roll(np.genfromtxt(designFL), 1, 1)))
        self.rawBM = np.genfromtxt(rawMapFile)
        self.resIDwithFreq = self.readInFrequencies(psFiles)
        self.fullBM = self.matchIDtoFreq()
        self.createFeedlines()
        self.chooseAppliedShift()


    def createFeedlines(self):
        if self.instrument.lower() == 'mec':
            self.fl1 = Feedline(1, self.fullBM, self.design, 3, 3)
            self.fl2 = Feedline(2, self.fullBM, self.design, 3, 3)
            self.fl3 = Feedline(3, self.fullBM, self.design, 3, 3)
            self.fl4 = Feedline(4, self.fullBM, self.design, 3, 3)
            self.fl5 = Feedline(5, self.fullBM, self.design, 3, 3)
            self.fl6 = Feedline(6, self.fullBM, self.design, 3, 3)
            self.fl7 = Feedline(7, self.fullBM, self.design, 3, 3)
            self.fl8 = Feedline(8, self.fullBM, self.design, 3, 3)
            self.fl9 = Feedline(9, self.fullBM, self.design, 3, 3)
            self.fl10 = Feedline(10, self.fullBM, self.design, 3, 3)
            self.feedlineShifts = np.array((self.fl1.bestshiftvector, self.fl2.bestshiftvector, self.fl3.bestshiftvector,
                                            self.fl4.bestshiftvector, self.fl5.bestshiftvector, self.fl6.bestshiftvector,
                                            self.fl7.bestshiftvector, self.fl8.bestshiftvector, self.fl9.bestshiftvector,
                                            self.fl10.bestshiftvector))
            self.shiftedBeamMap = np.concatenate((self.fl1.newFeedline, self.fl2.newFeedline, self.fl3.newFeedline,
                                                  self.fl4.newFeedline, self.fl5.newFeedline, self.fl6.newFeedline,
                                                  self.fl7.newFeedline, self.fl8.newFeedline, self.fl9.newFeedline,
                                                  self.fl10.newFeedline))
            self.designArray = np.concatenate((self.fl1.fitDesign, self.fl2.fitDesign, self.fl3.fitDesign,
                                               self.fl4.fitDesign, self.fl5.fitDesign, self.fl6.fitDesign,
                                               self.fl7.fitDesign, self.fl8.fitDesign, self.fl9.fitDesign,
                                               self.fl10.fitDesign), axis=1)
        elif self.instrument.lower() == 'darkness':
            self.fl1 = Feedline(1, self.fullBM, self.design, 3, 3)
            self.fl2 = Feedline(2, self.fullBM, self.design, 3, 3)
            self.fl3 = Feedline(3, self.fullBM, self.design, 3, 3)
            self.fl4 = Feedline(4, self.fullBM, self.design, 3, 3)
            self.fl5 = Feedline(5, self.fullBM, self.design, 3, 3)
            self.feedlineShifts = np.array((self.fl1.bestshiftvector, self.fl2.bestshiftvector, self.fl3.bestshiftvector,
                                            self.fl4.bestshiftvector, self.fl5.bestshiftvector))
            self.shiftedBeamMap = np.concatenate((self.fl1.newFeedline, self.fl2.newFeedline, self.fl3.newFeedline,
                                                  self.fl4.newFeedline, self.fl5.newFeedline))
            self.designArray = np.concatenate((self.fl1.fitDesign, self.fl2.fitDesign, self.fl3.fitDesign,
                                               self.fl4.fitDesign, self.fl5.fitDesign), axis=1)
        else:
            raise Exception('Provided instrument not implemented!')


    def chooseAppliedShift(self):
        self.appliedShift = np.array((np.nan, np.nan))
        xshifts = self.feedlineShifts[:, 0]
        xshifts = xshifts[~np.isnan(xshifts)]
        yshifts = self.feedlineShifts[:, 1]
        yshifts = yshifts[~np.isnan(yshifts)]
        for xshift in xshifts :
            if len(np.where(xshift == xshifts)[0]) >= len(xshifts):
                self.appliedShift[0] = xshift
        for yshift in yshifts:
            if len(np.where(yshift == yshifts)[0]) >= len(yshifts):
                self.appliedShift[1] = yshift




    def readInFrequencies(self, PowerSweepFiles):
        PowerSweeps = glob.glob(PowerSweepFiles)
        frequencies = np.loadtxt(PowerSweeps[0])
        for i in range(len(PowerSweeps) - 1):
            sweep = np.loadtxt(PowerSweeps[i + 1])
            frequencies = np.concatenate((frequencies, sweep))
        return frequencies


    def matchIDtoFreq(self):
        freqs = self.resIDwithFreq
        rawBeammap = self.rawBM
        rawBMwithFreqs = np.full((len(self.rawBM), len(self.rawBM[0])+1), np.nan)
        for i in range(len(rawBeammap)):
            rawBMwithFreqs[i][0], rawBMwithFreqs[i][1], rawBMwithFreqs[i][2], rawBMwithFreqs[i][3] = rawBeammap[i]
        for j in range(len(freqs)):
            idx = np.where(freqs[j][0] == rawBeammap[:, 0])[0][0]
            rawBMwithFreqs[idx][4] = (freqs[j][1] / (10 ** 6))
        return rawBMwithFreqs


class Feedline(object):
    def __init__(self, feedlinenumber, BMwithFreqs, designFL, maxXshift, maxYshift, flip=False, order=5):
        self.beammap = BMwithFreqs
        self.design = designFL
        self.flNum = feedlinenumber
        self.maxX = maxXshift
        self.maxY = maxYshift
        self.flipX = flip
        self.order = order
        self.feedline = self.getFeedline()
        self.resIDs = self.feedline[:, 0]
        self.flags = self.feedline[:, 1]
        self.xcoords = np.floor(self.feedline[:, 2])
        self.ycoords = np.floor(self.feedline[:, 3])
        self.frequencies = self.feedline[:, 4]
        if not np.all(np.isnan(self.xcoords)) and not np.all(np.isnan(self.ycoords)):
            self.getFreqExtrema()
            self.frequencies = self.frequencies - self.minF
            self.makeShiftCoords()
            self.findResidualsForAllShifts()
            self.getBestShift()
            self.newFeedline = np.transpose([self.feedline[:, 0], self.feedline[:, 1], self.bestshiftXcoords, self.bestshiftYcoords, self.frequencies])
            self.fitFrequencies()
            self.compareNearestNeighbors()
            self.countPixelsPlaced()
        else :
            self.newFeedline = self.feedline
            self.fitDesign = self.design
            self.bestshiftvector = np.array((np.nan, np.nan))


    def getFreqExtrema (self):
        self.minF = np.min(self.frequencies[~np.isnan(self.frequencies)])
        # self.maxF = np.max(self.frequencies[~np.isnan(self.frequencies)])
        # self.medianF = np.median(self.frequencies[~np.isnan(self.frequencies)])
        # self.meanF = np.mean(self.frequencies[~np.isnan(self.frequencies)])


    def getFeedline (self):
        tempmap = np.copy(self.beammap)
        feedline = tempmap[np.where(self.flNum == np.floor(tempmap[:, 0] / 10000))[0]]
        return feedline


    def makeShiftCoords (self):
        self.xshifts = np.linspace(-1 * self.maxX, self.maxX, (2 * self.maxX) + 1).astype(int)
        self.yshifts = np.linspace(-1 * self.maxY, self.maxY, (2 * self.maxY) + 1).astype(int)
        self.shiftedXcoords = np.full((len(self.yshifts), len(self.xshifts), len(self.xcoords)), float('NaN'))
        self.shiftedYcoords = np.full((len(self.yshifts), len(self.xshifts), len(self.ycoords)), float('NaN'))
        for i in self.yshifts:
            for j in self.xshifts:
                self.shiftedXcoords[i][j] = self.xcoords + self.xshifts[j]
                self.shiftedYcoords[i][j] = self.ycoords + self.yshifts[i]


    def isonarrayY(self, ycoord):
        if 0 <= int(ycoord) <= 145:
            return True
        return False


    def isincorrectfeedlineX(self, xcoord, feedlinenumber, flipX=False):
        if flipX:
            if feedlinenumber == 1:
                if 126 <= np.floor(xcoord) <= 139:
                    return True
                else:
                    return False
            if feedlinenumber == 2:
                if 112 <= np.floor(xcoord) <= 125:
                    return True
                else:
                    return False
            if feedlinenumber == 3:
                if 98 <= np.floor(xcoord) <= 111:
                    return True
                else:
                    return False
            if feedlinenumber == 4:
                if 84 <= np.floor(xcoord) <= 97:
                    return True
                else:
                    return False
            if feedlinenumber == 5:
                if 70 <= np.floor(xcoord) <= 83:
                    return True
                else:
                    return False
            if feedlinenumber == 6:
                if 56 <= np.floor(xcoord) <= 69:
                    return True
                else:
                    return False
            if feedlinenumber == 7:
                if 42 <= np.floor(xcoord) <= 55:
                    return True
                else:
                    return False
            if feedlinenumber == 8:
                if 28 <= np.floor(xcoord) <= 41:
                    return True
                else:
                    return False
            if feedlinenumber == 9:
                if 14 <= np.floor(xcoord) <= 27:
                    return True
                else:
                    return False
            if feedlinenumber == 10:
                if 0 <= np.floor(xcoord) <= 13:
                    return True
                else:
                    return False
        else:
            if feedlinenumber == 10:
                if 126 <= np.floor(xcoord) <= 139:
                    return True
                else:
                    return False
            if feedlinenumber == 9:
                if 112 <= np.floor(xcoord) <= 125:
                    return True
                else:
                    return False
            if feedlinenumber == 8:
                if 98 <= np.floor(xcoord) <= 111:
                    return True
                else:
                    return False
            if feedlinenumber == 7:
                if 84 <= np.floor(xcoord) <= 97:
                    return True
                else:
                    return False
            if feedlinenumber == 6:
                if 70 <= np.floor(xcoord) <= 83:
                    return True
                else:
                    return False
            if feedlinenumber == 5:
                if 56 <= np.floor(xcoord) <= 69:
                    return True
                else:
                    return False
            if feedlinenumber == 4:
                if 42 <= np.floor(xcoord) <= 55:
                    return True
                else:
                    return False
            if feedlinenumber == 3:
                if 28 <= np.floor(xcoord) <= 41:
                    return True
                else:
                    return False
            if feedlinenumber == 2:
                if 14 <= np.floor(xcoord) <= 27:
                    return True
                else:
                    return False
            if feedlinenumber == 1:
                if 0 <= np.floor(xcoord) <= 13:
                    return True
                else:
                    return False


    def matchMeastoDes(self, xcoords, ycoords):
        temparray = []
        matchedf = []
        desf = []
        for i in range((len(xcoords))):
            if self.isincorrectfeedlineX(xcoords[i], self.flNum, self.flipX) and self.isonarrayY(ycoords[i]):
                if not np.isnan(xcoords[i]) and not np.isnan(ycoords[i]) and not np.isnan(self.frequencies[i]):
                    x = int(xcoords[i] % 14)
                    y = int(ycoords[i] % 146)
                    residual = self.design[y][x] - self.frequencies[i]
                    temparray.append(residual)
                    matchedf.append(self.frequencies[i])
                    desf.append(self.design[y][x])
            else:
                temparray.append(np.nan)
                matchedf.append(np.nan)
                desf.append(np.nan)

        return np.array(temparray), np.array(matchedf), np.array(desf)


    def findResidualsForAllShifts(self):
        self.residuals = np.full((len(self.yshifts), len(self.xshifts), len(self.xcoords)), np.nan)
        self.matchedfreqs = np.full((len(self.yshifts), len(self.xshifts), 2, len(self.xcoords)), np.nan)
        for i in range(len(self.yshifts)):
            for j in range(len(self.xshifts)):
                self.residuals[i][j] = self.matchMeastoDes(self.shiftedXcoords[i][j], self.shiftedYcoords[i][j])[0]
                self.matchedfreqs[i][j][0] = self.matchMeastoDes(self.shiftedXcoords[i][j], self.shiftedYcoords[i][j])[1]
                self.matchedfreqs[i][j][1] = self.matchMeastoDes(self.shiftedXcoords[i][j], self.shiftedYcoords[i][j])[2]


    def removeNaNsfromArray(self, array):
        array = array[~np.isnan(array)]
        return array


    def getBestShift(self):
        self.MAD_std = np.zeros(((2 * self.maxY + 1), (2 * self.maxX + 1)))
        self.std = np.zeros(((2 * self.maxY + 1), (2 * self.maxX + 1)))
        for i in range(len(self.yshifts)):
            for j in range(len(self.xshifts)):
                self.MAD_std[i][j] = mad_std(self.removeNaNsfromArray(self.residuals[i][j]))
                self.std[i][j] = np.std(self.removeNaNsfromArray(self.residuals[i][j]))
        MAD_idx = np.unravel_index(self.MAD_std.argmin(), self.MAD_std.shape)
        std_idx = np.unravel_index(self.std.argmin(), self.std.shape)
        if np.array_equal(MAD_idx, std_idx):
            self.bestshiftvector = np.array((self.xshifts[MAD_idx[1]], self.yshifts[MAD_idx[0]]))
            self.bestshiftXcoords = self.shiftedXcoords[MAD_idx[0]][MAD_idx[1]]
            self.bestshiftYcoords = self.shiftedYcoords[MAD_idx[0]][MAD_idx[1]]
            self.bestshiftResiduals = self.residuals[MAD_idx[0]][MAD_idx[1]]
            self.bestMatchedFreqs = self.matchedfreqs[MAD_idx[0]][MAD_idx[1]]
        else :
            self.bestshiftvector = np.array((0, 0))
            self.bestshiftXcoords = self.shiftedXcoords[(2 * self.maxY + 1) // 2][(2 * self.maxX + 1) // 2]
            self.bestshiftYcoords = self.shiftedYcoords[(2 * self.maxY + 1) // 2][(2 * self.maxX + 1) // 2]
            self.bestshiftResiduals = self.residuals[(2 * self.maxY + 1) // 2][(2 * self.maxX + 1) // 2]
            self.bestMatchedFreqs = self.matchedfreqs[(2 * self.maxY + 1) // 2][(2 * self.maxX + 1) // 2]


    def guessInitialParams(self):
        data = self.removeNaNsfromArray(self.bestMatchedFreqs[0])
        model = self.removeNaNsfromArray(self.bestMatchedFreqs[1])
        params = np.polyfit(model, data, self.order, full=True)[0]
        return params


    def makeLstSqResiduals(self, parameters):
        p = np.poly1d(parameters)
        data = self.removeNaNsfromArray(self.bestMatchedFreqs[0])
        model = self.removeNaNsfromArray(self.bestMatchedFreqs[1])
        error = data - p(model)
        return error


    def fitFrequencies(self):
        primaryGuess = self.guessInitialParams()
        self.leastSquaresSol = opt.least_squares(self.makeLstSqResiduals, primaryGuess)
        coeffs = np.poly1d(self.leastSquaresSol.x)
        self.fitDesign = coeffs(self.design)


    def compareNearestNeighbors(self):
        self.nearestNeighborFreqLocation = np.full((len(self.newFeedline), 2), np.nan)
        for i in range(len(self.newFeedline)):
            if not np.isnan(self.newFeedline[i][2]) and not np.isnan(self.newFeedline[i][3]) and not np.isnan(self.newFeedline[i][4]):
                self.nearestNeighborFreqLocation[i][0] = self.findNearestNeighborFrequency(self.newFeedline[i])[1] - 1
                self.nearestNeighborFreqLocation[i][1] = -1 * (self.findNearestNeighborFrequency(self.newFeedline[i])[0] - 1)

        xvals = self.nearestNeighborFreqLocation[:, 0]
        yvals = self.nearestNeighborFreqLocation[:, 1]

        tl = len(np.where((xvals == -1) & (yvals == -1))[0])
        t = len(np.where((xvals == 0) & (yvals == -1))[0])
        tr = len(np.where((xvals == 1) & (yvals == -1))[0])
        l = len(np.where((xvals == -1) & (yvals == 0))[0])
        c = len(np.where((xvals == 0) & (yvals == 0))[0])
        r = len(np.where((xvals == 1) & (yvals == 0))[0])
        bl = len(np.where((xvals == -1) & (yvals == 1))[0])
        b = len(np.where((xvals == 0) & (yvals == 1))[0])
        br = len(np.where((xvals == 1) & (yvals == 1))[0])
        self.wellPlacedPixels = c
        self.totalPlacedPixels = tl + t + tr + l + c + r + bl + b + br


    def findNearestNeighborFrequency (self, resonator):
        resX = int(resonator[2]) % 14
        resXp1 = int(resX+1) % 14
        resXm1 = int(resX-1) % 14
        resY = int(resonator[3]) % 146
        resYp1 = int(resY+1) % 146
        resYm1 = int(resY-1) % 146
        nearestneighborfreqs = [[self.fitDesign[resYm1][resXm1], self.fitDesign[resYm1][resX], self.fitDesign[resYm1][resXp1]],
                                [self.fitDesign[resY][resXm1], self.fitDesign[resY][resX], self.fitDesign[resY][resXp1]],
                                [self.fitDesign[resYp1][resXm1], self.fitDesign[resYp1][resX], self.fitDesign[resYp1][resXp1]]]
        neighborresids = np.abs(nearestneighborfreqs - resonator[4])
        min_place = np.unravel_index(neighborresids.argmin(), neighborresids.shape)
        return min_place


    def plotNearestNeighborInfo(self):
        u = self.nearestNeighborFreqLocation[:, 0]
        v = self.nearestNeighborFreqLocation[:, 1]

        tl = len(np.where((u == -1) & (v == -1))[0])
        t = len(np.where((u == 0) & (v == -1))[0])
        tr = len(np.where((u == 1) & (v == -1))[0])
        l = len(np.where((u == -1) & (v == 0))[0])
        c = len(np.where((u == 0) & (v == 0))[0])
        r = len(np.where((u == 1) & (v == 0))[0])
        bl = len(np.where((u == -1) & (v == 1))[0])
        b = len(np.where((u == 0) & (v == 1))[0])
        br = len(np.where((u == 1) & (v == 1))[0])

        heights = np.array([[tl, t, tr], [l, c, r], [bl, b, br]])
        plt.imshow(heights, extent=[-heights.shape[1]/2., heights.shape[1]/2., -heights.shape[0]/2., heights.shape[0]/2. ])
        plt.colorbar()
        plt.show()


    def nearestNeighborQuiver(self):
        x = self.removeNaNsfromArray(self.newFeedline[:, 2])
        y = self.removeNaNsfromArray(self.newFeedline[:, 3])
        u = self.removeNaNsfromArray(self.nearestNeighborFreqLocation[:, 1])
        v = self.removeNaNsfromArray(self.nearestNeighborFreqLocation[:, 0])
        plt.quiver(x, y, u, v, angles='xy', scale_units='xy', scale=1)
        plt.show()


    def countPixelsPlaced(self):
        counter = 0
        for i in self.feedline:
            if i[1] == 0 and not np.isnan(i[2]) and not np.isnan(i[3]):
                counter = counter + 1
        self.placedPixels = counter


if __name__ == '__main__':

    designFlPath = 'mec_feedline.txt'
    rawBeammapPath = r'beammapTestData\newtest\RawMapV1.txt'
    powerSweepPath = r'beammapTestData\newtest\ps*.txt'
    feedlinesRead = [1, 5, 6, 7, 8, 9, 10]


    shifter = BeammapShifter(designFlPath, rawBeammapPath, powerSweepPath, "MEC")

