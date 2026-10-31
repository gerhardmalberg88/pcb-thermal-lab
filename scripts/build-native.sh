#!/usr/bin/env bash
# Reproducible local CPU installation; useful before container builds and for debugging.
set -euo pipefail
LAB_ROOT=$(cd "$(dirname "$0")/.." && pwd)
ELMER_SOURCE="$LAB_ROOT/.cache/src/elmerfem-5a8de867068be0568f09af40fb90fee300dfbede"
ELMER_PREFIX="$LAB_ROOT/.cache/native/elmer"
cmake -S "$ELMER_SOURCE" -B "$LAB_ROOT/.cache/build/elmer-cpu" -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$ELMER_PREFIX" \
  -DCMAKE_PREFIX_PATH="$LAB_ROOT/.cache/qt-root/usr" \
  -DWITH_MPI=ON -DWITH_OpenMP=ON -DWITH_Hypre=ON -DWITH_UMFPACK=ON \
  -DWITH_CHOLMOD=ON -DCHOLMOD_INCLUDE_DIR=/usr/include/suitesparse \
  -DCHOLMOD_LIBRARY=/usr/lib/x86_64-linux-gnu/libcholmod.so -DSPQR_LIBRARY=/usr/lib/x86_64-linux-gnu/libspqr.so \
  -DHypre_INCLUDE_DIR=/usr/include/hypre -DHypre_LIBRARY=/usr/lib/x86_64-linux-gnu/libHYPRE.so \
  -DWITH_ELMERGUI=ON -DWITH_QT5=ON -DWITH_QWT=ON -DWITH_VTK=OFF \
  -DWITH_OCC=OFF -DWITH_ELMERPOST=OFF -DWITH_ELMERGUITESTER=OFF \
  '-DINCLUDE_ELMER_MODULES=HeatSolve;HeatSolveVec;FluxSolver;SaveData;ResultOutputSolve' \
  -DBUILD_TESTING=OFF -DHAVE_QP=OFF
cmake --build "$LAB_ROOT/.cache/build/elmer-cpu" --parallel "${BUILD_JOBS:-2}"
cmake --install "$LAB_ROOT/.cache/build/elmer-cpu"
mkdir -p "$LAB_ROOT/env/locks/native-cpu"
dpkg-query -W > "$LAB_ROOT/env/locks/native-cpu/apt-packages.txt"
cp "$LAB_ROOT/.cache/build/elmer-cpu/CMakeCache.txt" "$LAB_ROOT/env/locks/native-cpu/"
printf 'Elmer installed at %s\n' "$ELMER_PREFIX"
