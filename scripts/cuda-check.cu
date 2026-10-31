#include <cuda_runtime.h>
#include <cstdio>
__global__ void check(double *p) { p[threadIdx.x] = threadIdx.x * 2.0; }
int main() {
  int count=0;
  cudaError_t e=cudaGetDeviceCount(&count);
  if(e!=cudaSuccess || count<1) { std::fprintf(stderr,"CUDA unavailable: %s\n",cudaGetErrorString(e)); return 1; }
  for(int device=0;device<count;device++) {
    if(cudaSetDevice(device)!=cudaSuccess)return 2;
    double *p;double result[32];
    if(cudaMalloc(&p,sizeof(result))!=cudaSuccess)return 3;
    check<<<1,32>>>(p);
    if(cudaDeviceSynchronize()!=cudaSuccess)return 4;
    if(cudaMemcpy(result,p,sizeof(result),cudaMemcpyDeviceToHost)!=cudaSuccess)return 5;
    cudaFree(p);
    for(int i=0;i<32;i++)if(result[i]!=i*2.0)return 6;
  }
  std::printf("CUDA compute and memory preflight passed on %d device(s)\n",count);
  return 0;
}
