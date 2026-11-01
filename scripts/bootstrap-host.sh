#!/usr/bin/env bash
# Host prerequisites for Ubuntu 24.04. Does not install a graphics driver.
set -euo pipefail
sudo apt-get update
sudo apt-get install -y podman uidmap slirp4netns fuse-overlayfs \
  build-essential gfortran cmake ninja-build libopenmpi-dev openmpi-bin \
  libblas-dev liblapack-dev libhypre-dev libmetis-dev libparmetis-dev \
  libsuitesparse-dev qtbase5-dev qtscript5-dev libqt5svg5-dev libqt5opengl5-dev libqwt-qt5-dev \
  libocct-data-exchange-dev libocct-visualization-dev \
  python3-venv python3-pip python3-shapely python3-scipy python3-numpy \
  python3-matplotlib python3-gmsh gmsh paraview python3-paraview \
  xvfb xauth curl unzip
printf '%s\n' 'Host prerequisites installed. The lab builds Elmer separately.'
