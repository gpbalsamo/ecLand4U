# ecLand4U

<p align="center">
  <img src="ecLand4U.png" alt="ecLand4U overview" width="850">
</p>

**ecLand4U** is a practical gateway into ECMWF's open-source ecLand code.

It supports users who want to install, run, test and analyse ecLand, with examples for:

- macOS installation
- MPI configuration
- ecLand build and tests
- site and offline workflows
- landgram diagnostics
- research and development use cases

The project is based around the official ECMWF ecLand repository:

https://github.com/ecmwf-ifs/ecland

## Purpose

The goal of **ecLand4U** is to make it easier for students, researchers, PhD candidates, postdocs and collaborators to get started with ecLand, from installation to first experiments and diagnostics.

The material is intended as a practical support layer around the official ecLand codebase, with a focus on:

- reproducible installation notes;
- simple workflows for running ecLand;
- practical diagnostics and plotting;
- research-to-operation examples;
- land, snow, vegetation, carbon and hydrology use cases.

## Getting started

Clone the official ecLand repository:

```bash
git clone https://github.com/ecmwf-ifs/ecland.git
cd ecland
For macOS users, the recommended first steps are:
brew install cmake open-mpi netcdf netcdf-fortran hdf5 eccodes pkg-config git wget python
Configure MPI explicitly before building:
export MPI_HOME=$(brew --prefix open-mpi)
export PATH="$MPI_HOME/bin:$PATH"
export CC=mpicc
export CXX=mpicxx
export FC=mpifort
export DR_HOOK_ASSERT_MPI_INITIALIZED=0
Then build ecLand:
./ecland-bundle build
Run the ecLand tests:
cd build
ctest -R ecland --output-on-failure
Landgram diagnostics
The landgram.py diagnostic can be used to inspect ecLand test output, for example:
landgram.py \
  --input "./o_*.nc" \
  --lat 42.5378 \
  --lon -72.1715 \
  --loc "Harvard Forest" \
  --out landgram_HarvardForest.png
Make sure the ecLand namelist enables output writing before running diagnostics.
Status
This repository is under active development.
