#include <stdlib.h>
#include <stdio.h>
#include <unistd.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <inttypes.h>
#include <fcntl.h>
#include <semaphore.h>
#include <string.h>
#include <errno.h>
#include <time.h>

// Compile shared object with: gcc -shared -o libmkidshm.so -fPIC mkidshm.c -lrt -lpthread

#ifndef MKIDSHM_H
#define MKIDSHM_H

#ifdef __cplusplus
extern "C" {

#endif

#define N_DONE_SEMS 10
#define MKIDSHM_VERSION 3
#define TIMEDWAIT_FUDGE 500 //half ms
#define STRBUFLEN 80
#define WVLIDLEN 150
typedef int image_t; //can mess around with changing this w/o many subsitutions
typedef float coeff_t;

typedef struct{
    //metadata
    uint32_t version;

    uint32_t nCols;
    uint32_t nRows;
    uint32_t useWvl; //ignore wavelength information if 0
    uint32_t nWvlBins;
    uint32_t useEdgeBins; //if 1 add bins for photons out of range
    uint32_t wvlStart;
    uint32_t wvlStop;
    uint32_t valid; //if 0 image is invalid b/c params changed during integration
    uint64_t startTime; //start timestamp of current integration (same as firmware time)
    uint64_t integrationTime; //integration time in half-ms
    uint32_t takingImage;
    char name[STRBUFLEN];
    char imageBufferName[STRBUFLEN]; //form: /imgbuffername (in /dev/shm)
    char takeImageSemName[STRBUFLEN];
    char doneImageSemName[STRBUFLEN];
    char wavecalID[WVLIDLEN];

} MKID_IMAGE_METADATA;


typedef struct{
    MKID_IMAGE_METADATA *md; //pointer to shared memory buffer

    // For nCounts in pixel (x, y) and wavelength bin i:
    //  image[i*nCols*nRows + y*nCols + x]
    image_t *image; //pointer to shared memory buffer

    sem_t *takeImageSem; //post to start integration
    sem_t **doneImageSemList; //post when integration is done

} MKID_IMAGE;


typedef struct{
    // coordinates
    uint8_t x;
    uint8_t y;

    uint64_t time; //arrival time (could also shorten and make relative)
    coeff_t wvl; //wavelength

} MKID_PHOTON_EVENT;

typedef struct{
    uint32_t bufferSize; //Size of circular buffer
    uint32_t endInd; //index of last write
    int writing; //1 if currently writing event
    int nCycles; //increment on each complete cycle of buffer
    sem_t **newPhotonSemList;

} MKID_EVENT_BUFFER_METADATA;

typedef struct{
    MKID_EVENT_BUFFER_METADATA *md;
    MKID_PHOTON_EVENT *eventBuffer;

} MKID_EVENT_BUFFER;


int MKIDShmImage_open(MKID_IMAGE *imageStruct, const char *imgName);
int MKIDShmImage_close(MKID_IMAGE *imageStruct);
int MKIDShmImage_create(MKID_IMAGE_METADATA *imageMetadata, const char *imgName, MKID_IMAGE *outputImage);
int MKIDShmImage_populateMD(MKID_IMAGE_METADATA *imageMetadata, const char *name, int nCols, int nRows, int useWvl, int nWvlBins, int useEdgeBins, int wvlStart, int wvlStop);
void MKIDShmImage_startIntegration(MKID_IMAGE *image, uint64_t startTime, uint64_t integrationTime);
void MKIDShmImage_wait(MKID_IMAGE *image, int semInd);

//time is in half-ms, cancels integration if stopImage is 1
int MKIDShmImage_timedwait(MKID_IMAGE *image, int semInd, int time, int stopImage);
int MKIDShmImage_checkIfDone(MKID_IMAGE *image, int semInd);
void MKIDShmImage_postDoneSem(MKID_IMAGE *image, int semInd);
void MKIDShmImage_copy(MKID_IMAGE *image, image_t *ouputBuffer);
void MKIDShmImage_setWvlRange(MKID_IMAGE *image, int wvlStart, int wvlStop);
//void MKIDShmImage_setInvalid(MKID_IMAGE *image);
//void MKIDShmImage_setValid(MKID_IMAGE *image);


void *openShmFile(const char *shmName, size_t size, int create);

#ifdef __cplusplus
}

#endif

#endif
