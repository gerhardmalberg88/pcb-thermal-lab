#!/usr/bin/env python3
"""Auditable compatibility/correctness fixes for the pinned Elmer 26.1 AMGX bridge.

Upstream source retains its license. Fail on unexpected source revisions.
CUDA 12.9 removed the unused NVTX v2 library; NVTX v3 is header-only.
"""
from pathlib import Path
import re
import sys

root = Path(sys.argv[1])
cmake = root / 'cmake/Modules/FindAMGX.cmake'
text = cmake.read_text()
assert text.count(' ${CUDA_nvToolsExt_LIBRARY}') == 1
cmake.write_text(text.replace(' ${CUDA_nvToolsExt_LIBRARY}', ''))
bridge = root / 'fem/src/amgx.c'
text = bridge.read_text()
assert text.count('for(i<0; i<n; i++ )') == 1
text = text.replace('for(i<0; i<n; i++ )', 'for(i=0; i<n; i++ )')
# Upstream leaves the convergence-status check commented out. Never accept a
# failed AMGX solve merely because Elmer later prints its completion marker.
old = '//    AMGX_solver_get_status(ptr->solver, &status);'
assert text.count(old) == 1
text = text.replace(old, '''    AMGX_SAFE_CALL(AMGX_solver_get_status(ptr->solver, &status));
    if (status != AMGX_SOLVE_SUCCESS) {
      fprintf(stderr, "FATAL:: AMGX failed to converge (status %d)\\n", status);
      MPI_Abort(MPI_COMM_WORLD, EXIT_FAILURE);
      exit(EXIT_FAILURE);
    }''')
# Check API return codes too, including uploads, setup and solve.
text = re.sub(r'^(\s*)(AMGX_(?!SAFE_CALL)\w+\([^;\n]*\));', r'\1AMGX_SAFE_CALL(\2);', text, flags=re.M)
bridge.write_text(text)
print('Applied pinned NVTX compatibility, RHS initialization and AMGX failure checks')
