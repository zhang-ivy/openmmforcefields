#!/usr/bin/env python
from __future__ import print_function
import sys
import parmed as pmd
from simtk import openmm as mm, unit as u
from simtk.openmm import app
import numpy as np
import time
import os, re

prefix = sys.argv[1] # Directory where CHARMM input files are stored
filename = 'step3_pbcsetup'
#filename = 'step1_pdbreader'

# Run CHARMM energy and force calculation
import subprocess
print('Running CHARMM in docker container (may take a minute)...')
command = "docker run -i -v `pwd`:/mnt -t omnia/charmm-lite:c40b1 /mnt/%s.sh" % prefix
charmm_output = subprocess.check_output(command, shell=True, universal_newlines=True)

# Parse CHARMM energy and force output
"""
ENER ENR:  Eval#     ENERgy      Delta-E         GRMS
ENER INTERN:          BONDs       ANGLes       UREY-b    DIHEdrals    IMPRopers
ENER CROSS:           CMAPs        PMF1D        PMF2D        PRIMO
ENER EXTERN:        VDWaals         ELEC       HBONds          ASP         USER
ENER IMAGES:        IMNBvdw       IMELec       IMHBnd       RXNField    EXTElec
ENER EWALD:          EWKSum       EWSElf       EWEXcl       EWQCor       EWUTil
 ----------       ---------    ---------    ---------    ---------    ---------
ENER>        0-163043.99835      0.00000      5.02279
ENER INTERN>     6337.99813   4236.12181     54.30685   1726.66813     21.86301
ENER CROSS>       -21.48984      0.00000      0.00000      0.00000
ENER EXTERN>    20161.20647-164737.82886      0.00000      0.00000      0.00000
ENER IMAGES>      243.39096  -5318.48694      0.00000      0.00000      0.00000
ENER EWALD>       4130.5989-1021718.0599  991839.7129       0.0000       0.0000
"""
print('Parsing CHARMM output...')
keys = list()
values = list()
for line in charmm_output.split('\n'):
    if line.startswith('ENER'):
        if ':' in line:
            elements = line.split(':')
            tokens = elements[1].split()
            for token in tokens:
                token = token.strip()
                keys.append(token)
        elif '>' in line:
            elements = line.split('>')
            tokens = re.split('(-|\+)|\s+', elements[1].strip())
            index = 0
            while index < len(tokens):
                if (tokens[index] is None) or (len(tokens[index])==0):
                    index += 1
                elif tokens[index] in ['+', '-']:
                    token = (tokens[index] + tokens[index+1]).strip()
                    value = float(token)
                    index += 2
                    values.append(value)
                else:
                    token = tokens[index].strip()
                    value = float(token)
                    index += 1
                    values.append(value)

from collections import OrderedDict
charmm_energy_components = OrderedDict()
for (key, value) in zip(keys, values):
    charmm_energy_components[key] = value
print(charmm_energy_components)

# Read forces
" CHARMM>    PRINT COOR COMP"
"""
 CHARMM>    PRINT COOR COMP

          COORDINATE FILE MODULE
 TITLE>  * GENERATED BY CHARMM-GUI (HTTP://WWW.CHARMM-GUI.ORG) V1.8 ON MAY, 05. 2016.
 TITLE>  * INPUT FILE FOR NPT DYNAMICS OF SOLVATED GLOBULAR PROTEIN
 TITLE>  *
     48112  EXT
         1         1  SER       N               7.2343288005      -19.3438455283      -16.1757927048  PROA      3               0.0000000000
         2         1  SER       HT1             2.4092138846       -0.5796144732        1.9424868065  PROA      3               0.0000000000
         3         1  SER       HT2             1.1212192343       -1.2813090526       -0.3294225705  PROA      3               0.0000000000
         4         1  SER       HT3             1.7474879735       -0.3449442699       -0.4467440973  PROA      3               0.0000000000
         5         1  SER       CA             -1.7381606984       12.3693196894       11.3198523175  PROA      3               0.0000000000
"""
print('Parsing CHARMM forces...')
lines = charmm_output.split('\n')
for index in range(len(lines)):
    if 'CHARMM>    print coor comp' in lines[index]:
        elements = lines[index+6].split()
        natoms = int(elements[0])
        firstline = index + 7
        break
charmm_forces = np.zeros([natoms,3], np.float64)
for (atom_index, line_index) in enumerate(range(firstline,firstline+natoms)):
    line = lines[line_index]
    elements = lines[line_index].split()
    charmm_forces[atom_index,0] = -float(elements[4])
    charmm_forces[atom_index,1] = -float(elements[5])
    charmm_forces[atom_index,2] = -float(elements[6])
charmm_forces = u.Quantity(charmm_forces, u.kilocalories_per_mole / u.angstroms)

# Read box size and PME parameters
"""
 SET XTLTYPE  = CUBIC
 SET A = 80
 SET B = 80
 SET C = 80
 SET ALPHA = 90.0
 SET BETA  = 90.0
 SET GAMMA = 90.0
 SET FFTX     = 90
 SET FFTY     = 90
 SET FFTZ     = 90
 SET POSID = POT
 SET NEGID = CLA
 SET XCEN = 0
 SET YCEN = 0
 SET ZCEN = 0
"""
infile = open(os.path.join(prefix, filename + '.str'), 'r')
lines = infile.readlines()
for line in lines:
    tokens = line.split()
    if tokens[1] == 'A':
        a = float(tokens[3]) * u.angstroms
    if tokens[1] == 'B':
        b = float(tokens[3]) * u.angstroms
    if tokens[1] == 'C':
        c = float(tokens[3]) * u.angstroms
    if tokens[1] == 'FFTX':
        fftx = int(tokens[3])
    if tokens[1] == 'FFTY':
        ffty = int(tokens[3])
    if tokens[1] == 'FFTZ':
        fftz = int(tokens[3])

# Load topology and coordinates
psf = app.CharmmPsfFile(os.path.join(prefix, filename + '.psf'))
# Taken from output of CHARMM run
psf.setBox(a, b, c)
crd = app.CharmmCrdFile(os.path.join(prefix, filename + '.crd'))
topology, positions = psf.topology, crd.positions

#params = app.CharmmParameterSet(
#    os.path.join(prefix, 'toppar/par_all36_prot.prm'),
#    os.path.join(prefix, 'toppar/par_all36_na.prm'),
#    os.path.join(prefix, 'toppar/toppar_water_ions.str'))
#pdb = app.PDBFile(os.path.join(prefix, filename + '.pdb'))
#topology, positions = pdb.topology, pdb.positions # DEBUG

# Delete H-H bonds from waters and retreive updated topology and positions
modeller = app.Modeller(topology, positions)
hhbonds = [b for b in modeller.topology.bonds() if b[0].element == app.element.hydrogen and b[1].element == app.element.hydrogen]
modeller.delete(hhbonds)
topology, positions = modeller.topology, modeller.positions

#app.PDBFile.writeFile(psf.topology, crd.positions, open('step3_pbcsetup.pdb', 'w')) # DEBUG

#system = psf.createSystem(params, nonbondedMethod=app.PME,
#        nonbondedCutoff=12*u.angstroms, switchDistance=10*u.angstroms)

# Load forcefield
print('Loading ForceField with charmm36.xml...')
#ffxml_filenames = ['charmm36.xml', 'charmm36/water.xml'] # OpenMM install path
ffxml_filenames = ['ffxml/charmm36_nowaters.xml', 'ffxml/waters_ions_default.xml'] # Local path
forcefield = app.ForceField(*ffxml_filenames)
print('Creating System...')
initial_time = time.time()
system = forcefield.createSystem(topology, nonbondedMethod=app.PME,
        rigidWater=True,
        nonbondedCutoff=12*u.angstroms, switchDistance=10*u.angstroms)
final_time = time.time()
elapsed_time = final_time - initial_time
print('   System creation took %.3f s' % elapsed_time)

for force in system.getForces():
    if isinstance(force, mm.CustomNonbondedForce):
        #print('CustomNonbondedForce: %s' % force.getUseSwitchingFunction())
        #print('LRC? %s' % force.getUseLongRangeCorrection())
        force.setUseLongRangeCorrection(False)
    elif isinstance(force, mm.NonbondedForce):
        #print('NonbondedForce: %s' % force.getUseSwitchingFunction())
        #print('LRC? %s' % force.getUseDispersionCorrection())
        force.setUseDispersionCorrection(False)
        force.setPMEParameters(1.0/0.34, fftx, ffty, fftz) # NOTE: These are hard-coded!
pmdparm = pmd.load_file(os.path.join(prefix,'step3_pbcsetup.psf'))
pmdparm.positions = positions
pmdparm.box = [a/u.angstroms, b/u.angstroms, c/u.angstroms, 90, 90, 90]

# Get OpenMM forces.
force_unit = u.kilocalories_per_mole/u.angstroms
integrator = mm.VerletIntegrator(1.0 * u.femtoseconds)
context = mm.Context(system, integrator)
context.setPositions(positions)
omm_energy = context.getState(getEnergy=True).getPotentialEnergy()
print('OpenMM total energy: %f kcal/mol' % (omm_energy / u.kilocalories_per_mole))
omm_forces = context.getState(getForces=True).getForces(asNumpy=True)

# Form CHARMM energy components
charmm_energy = dict()
charmm_energy['Bond + UB'] = \
    + charmm_energy_components['BONDs'] * u.kilocalories_per_mole \
    + charmm_energy_components['UREY-b'] * u.kilocalories_per_mole
charmm_energy['Angle'] = charmm_energy_components['ANGLes'] * u.kilocalories_per_mole
charmm_energy['Dihedrals'] = charmm_energy_components['DIHEdrals'] * u.kilocalories_per_mole
charmm_energy['Impropers'] = charmm_energy_components['IMPRopers'] * u.kilocalories_per_mole
if 'CMAPs' in charmm_energy_components:
    charmm_energy['CMAP'] = charmm_energy_components['CMAPs'] * u.kilocalories_per_mole
charmm_energy['Lennard-Jones'] = \
    + charmm_energy_components['VDWaals'] * u.kilocalories_per_mole \
    + charmm_energy_components['IMNBvdw'] * u.kilocalories_per_mole
charmm_energy['Electrostatics'] = \
    + charmm_energy_components['ELEC'] * u.kilocalories_per_mole \
    + charmm_energy_components['IMELec'] * u.kilocalories_per_mole \
    + charmm_energy_components['EWKSum'] * u.kilocalories_per_mole \
    + charmm_energy_components['EWSElf'] * u.kilocalories_per_mole \
    + charmm_energy_components['EWEXcl'] * u.kilocalories_per_mole

charmm_energy['Total'] = charmm_energy_components['ENERgy'] * u.kilocalories_per_mole


total = 0.0 * u.kilocalories_per_mole
if 'CMAPs' in charmm_energy_components:
    force_terms = ['Bond + UB', 'Angle', 'Dihedrals', 'Impropers', 'CMAP', 'Lennard-Jones', 'Electrostatics']
else:
    force_terms = ['Bond + UB', 'Angle', 'Dihedrals', 'Impropers', 'Lennard-Jones', 'Electrostatics']
for key in force_terms:
    total += charmm_energy[key]
print('CHARMM total energy: ', charmm_energy['Total'], total)

# Get OpenMM energies as an ordered list of tuples
omm_e = pmd.openmm.energy_decomposition_system(pmdparm, system, nrg=u.kilocalories_per_mole)
# Attach proper units corresponding to ParmEd units
for (index, (name, e)) in enumerate(omm_e):
    omm_e[index] = (name, e * u.kilocalories_per_mole)

# Compile OpenMM energy components
openmm_energy = dict()
openmm_energy['Bond + UB'] = omm_e[0][1]
openmm_energy['Angle'] = omm_e[1][1]
openmm_energy['Dihedrals'] = omm_e[2][1]
openmm_energy['Impropers'] = omm_e[3][1]
if 'CMAP' in force_terms:
    openmm_energy['CMAP'] = omm_e[4][1]
openmm_energy['Electrostatics'] = omm_e[5][1]
openmm_energy['Lennard-Jones'] = omm_e[6][1] + omm_e[7][1]
openmm_energy['Total'] = 0.0 * u.kilojoules_per_mole
for term in force_terms:
    openmm_energy['Total'] += openmm_energy[term]

print('OpenMM Energy is %s' % omm_e)

# Now do the comparisons
print('Output in kJ/mol')
print('%-20s | %-15s | %-15s' % ('Component', 'CHARMM', 'OpenMM'))
print('-'*56)
total = 0
for name in force_terms:
    print('%-20s | %15.2f | %15.2f' % (name, charmm_energy[name] / u.kilojoules_per_mole, openmm_energy[name] / u.kilojoules_per_mole))
print('-'*56)
print('%-20s | %15.2f | %15.2f' % ('Total', charmm_energy['Total'] / u.kilojoules_per_mole, openmm_energy['Total'] / u.kilojoules_per_mole))
print('-'*56)

# Compare forces
proj = (charmm_forces * omm_forces).sum(axis=1) / (omm_forces * omm_forces).sum(axis=1)
ref = np.sqrt((omm_forces**2).sum(axis=1))
reldiff = np.sqrt(((charmm_forces - omm_forces)**2).sum(axis=1)) / ref
maxdiff = reldiff.max()
meandiff = reldiff.mean()
mediandiff = np.median(reldiff)

print('Max Relative F diff:    %15.6E' % maxdiff)
print('Mean Relative F diff:   %15.6E' % meandiff)
print('Median Relative F diff: %15.6E' % mediandiff)
print('-'*56)
print('Projection of Amber and OpenMM force:')
print('-'*56)
print('Average: %15.6f' % proj.mean())
print('Min:     %15.6f' % proj.min())
print('Max:     %15.6f' % proj.max())
