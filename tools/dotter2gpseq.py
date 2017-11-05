#!/usr/bin/env python
# -*- coding: utf-8 -*-

# ------------------------------------------------------------------------------
# 
# Author: Gabriele Girelli
# Email: gigi.ga90@gmail.com
# Version: 1.2.0
# Date: 20170718
# Project: GPSeq
# Description: Calculate radial position of dots in cells
# 
# Changelog:
#  v1.2.0 - 20171105: dilation, allele labeling, parallelization.
#  v1.1.1 - 20171020: fixed parameter description.
#  v1.1.0 - 20170830: added G1 cells selection.
#  v1.0.0 - 20170718: first implementation.
#  
# Todo:
#  - Parallelize when possible.
#  - Allow nucleus dilation or distance from lamina for out-of-nucleus dots.
# 
# ------------------------------------------------------------------------------



# DEPENDENCIES =================================================================

import argparse
from joblib import Parallel, delayed
import math
import matplotlib
matplotlib.use('ps')
import matplotlib.pyplot as plt
import multiprocessing
import numpy as np
import os
import pandas as pd
from scipy.ndimage.morphology import distance_transform_edt
import skimage.io as io
from skimage.measure import label
from skimage.morphology import dilation, cube
import sys

import pygpseq as gp
from pygpseq.wraps.nucleus import Nucleus
from pygpseq.tools import image as imt
from pygpseq.tools import io as iot
from pygpseq.tools import plot
from pygpseq.tools import stat as stt

# PARAMETERS ===================================================================

# Add script description
parser = argparse.ArgumentParser(description = '''
Calculate radial position of dots in cells. Use the -s option to trigger nuclei
recognition and G1 selection: a column will be added flagging dots belonging to
cells expected to be in G1. The G1 selection is actually a selection of the most
represented cell sub-population based on flatten area and integral of DNA stain
intensity. In other words, it will selected the most represented cell cycle
phase in your cell population (generally, G1). Please, note that nuclei
recognition and G1 selection are time consuming steps and require a large number
of nuclei to work properly (i.e., more than 300). Images are expected to follow
DOTTER filename notation: "channel_series.tif".
''')

# Add mandatory arguments
parser.add_argument('dotCoords', type = str, nargs = 1,
	help = 'Dot coordinates table generated by DOTTER.')
parser.add_argument('imgFolder', type = str, nargs = 1,
	help = 'Path to folder containing deconvolved tiff images.')
parser.add_argument('outFolder', type = str, nargs = 1,
	help = 'Path to output folder (created if does not exist).')

# Optional parameters
parser.add_argument('-a', '--aspect', type = float, nargs = 3,
	help = """Physical size of Z, Y and X voxel sides.
	Default: 300.0 130.0 130.0""",
	metavar = ('Z', 'Y', 'X'), default = [300., 130., 130.])
parser.add_argument('-d', '--delim', type = str, nargs = 1,
	help = """Input table delimiter. Default: ','""", default = [','])
parser.add_argument('--dilate', type = int, nargs = 1,
	help = """Number of pixels for nuclear mask dilation. Default: 0""",
	default = [0])
parser.add_argument('-t', '--threads', type = int, nargs = 1,
	help = """Number of threads for parallelization. Default: 1""",
	default = [1])

# Add flags
parser.add_argument('-s',
	action = 'store_const', dest = 'sel',
	const = True, default = False,
	help = 'Perform nuclei recognition and G1 selection (time consuming).')
parser.add_argument('--noplot',
	action = 'store_const', dest = 'noplot',
	const = True, default = False,
	help = 'Do not produce any plots.')

# Parse arguments
args = parser.parse_args()

# Assign to in-script variables
dot_table_name = args.dotCoords[0]
dot_file_name = dot_table_name.split('/')[-1]
imdir = args.imgFolder[0]
aspect = args.aspect
(az, ay, ax) = aspect
outdir = args.outFolder[0]
doSel = args.sel
delim = args.delim[0]
noplot = args.noplot
dilate_factor = args.dilate[0]
ncores = args.threads[0]

# Params
seg_type = gp.const.SEG_3D
an_type = gp.const.AN_3D

# Additional checks
if not outdir[-1] == "/":
	while not os.path.isdir(outdir) and os.path.exists(outdir):
		outdir += "_"
	outdir += "/"
if not imdir[-1] in ['/\\']:
	imdir += "/"
maxncores = multiprocessing.cpu_count()
if maxncores < ncores:
	print("Lowered number of threads to maximum available: %d" % (maxncores))
	ncores = maxncores

# FUNCTIONS ====================================================================

def in_box(coords, box):
	''''''
	c = True
	for dim in range(len(coords)):
		c = c and coords[dim] >= box[dim][0] and coords[dim] <= box[dim][1]

	return c

def in_nucleus(n, s, coords):
	''''''
	if not n.s == s:
		return False
	
	return in_box(coords, n.box)

def save_mask_png(outpath, im, name, title):
	fig = plt.figure()
	if 3 == len(im.shape):
		plt.imshow(im.max(0).astype('u4'))
	else:
		plt.imshow(im.astype('u4'))
	plt.gca().get_xaxis().set_visible(False)
	plt.gca().get_yaxis().set_visible(False)
	plot.set_font_size(8)

	plt.title(title)

	# Export as png
	if not noplot: plot.export(outpath, 'png')

	# Close plot figure
	plt.close(fig)

def in_3d_box(box, coords):
	# Check if point is in a box
	# 
	# Args:
	# 	box (tuple): ((x0, x1), (y0, y1), (z0, z1)).
	# 	coords (tuple): (x, y, z).
	# 
	# Returns
	# 	bool
	cx = coords[0] >= box[0][0] and coords[0] <= box[0][1]
	cy = coords[1] >= box[1][0] and coords[1] <= box[1][1]
	cz = coords[2] >= box[2][0] and coords[2] <= box[2][1]
	return(cx and cy and cz)

def add_allele(data):
    # Add allele labels to DOTTER-based table with GPSeq-like centrality.
    # 
    # Labels:
    #   NaN : dot outside of cells.
    #   -1  : more than 2 dots per cell.
    #   0   : less than 2 dots per cell.
    #   1   : central dot.
    #   2   : peripheral dot.
    # 
    # Args:
    #   data (pd.DataFrame): DOTTER-based table with GPSeq-like centrality.
    #                        Required columns:
    #                           cell_ID, lamin_dist_norm, File, Channel
    #
    # Returns:
    #   pd.DataFrame: input data table with added Allele column (label).
    # 

    # Initial checks -----------------------------------------------------------

    # Check that the format corresponds
    if not type(data) == type(pd.DataFrame()):
        print("Input should be a DataFrame from the pandas library.")
        return(data)

    # Check that required columns are present
    req_cols = ['cell_ID', 'lamin_dist_norm', 'File', 'Channel']
    check_cols = [True for c in req_cols if c in data.columns.tolist()]
    if not all(check_cols):
        miss_cols = [req_cols[i]
            for i in range(len(req_cols)) if not check_cols[i]]
        print("Some required columns are missing: %s" % (", ".join(miss_cols),))
        return(data)

    # Universal index and dots in cells ----------------------------------------

    # Identify dots within cells
    validIdx = np.nonzero(data['cell_ID'])[0]

    # Assemble universal index
    data['universalID'] =  ["%s_%s_%s" % t for t in zip(
        data['File'].values, data['Channel'].values, data['cell_ID'].values
    )]

    # Count dots per universalID
    uID,  uCount = np.unique(data.loc[validIdx, 'universalID'],
        return_index = False, return_counts = True)
    IDmap = np.array(zip(data.loc[validIdx, 'universalID'],
        [dict(zip(uID, uCount))[ID]
        for ID in data.loc[validIdx, 'universalID']]))

    # Fill Allele column -------------------------------------------------------
    
    # Default value of np.nan for dots outside of nuclei
    data['Allele'] = np.nan

    # -1 if more than 2 dots
    data.loc[validIdx[IDmap[:,1].astype('i') > 2], 'Allele'] = -1

    #  0 if less than 2 dots
    data.loc[validIdx[IDmap[:,1].astype('i') == 1], 'Allele'] = 0

    # Iterate over 2-dots cases
    uID = np.unique(IDmap[IDmap[:,1].astype('i') == 2, 0]).tolist()
    for ID in uID:
        dotPair = data.loc[data['universalID'] == ID, :]
        data.loc[dotPair['lamin_dist_norm'].argmin(), 'Allele'] = 2 # Peripheral
        data.loc[dotPair['lamin_dist_norm'].argmax(), 'Allele'] = 1 # Central

    # Output -------------------------------------------------------------------
    return(data.drop('universalID', 1))

def analyze_field_of_view(ii, imfov, imdir, an_type, seg_type,
	maskdir, dilate_factor, aspect, t):
	# Logger for logpath
	logger = iot.IOinterface()

	(idx, impath) = list(imfov.items())[ii]
	print("  · '%s'..." % (impath,))
	msg = "  · '%s'...\n" % (impath,)
	subt_idx = np.where(t['File'] == idx)[0]

	# Read image
	msg = "   - Reading ...\n"
	im = io.imread(os.path.join(imdir, impath))[0]

	# Re-slice
	msg += "    > Re-slicing ...\n"
	im = imt.autoselect_time_frame(im)
	im = imt.slice_k_d_img(im, 3)

	# Get DNA scaling factor and rescale
	sf = imt.get_rescaling_factor([impath], basedir = imdir)
	im = (im / sf).astype('float')
	msg += "    > Re-scaling with factor %f...\n" % (sf,)

	# Pick first timeframe
	if 3 == len(im.shape) and 1 == im.shape[0]:
		im = im[0]

	# Binarize image -----------------------------------------------------------
	msg += "   - Binarizing...\n"
	binarization = gp.tools.binarize.Binarize(
		an_type=an_type,
		seg_type=seg_type,
		verbose = False
	)
	(imbin, thr, log) = binarization.run(im)
	msg += log

	# Find nuclei --------------------------------------------------------------
	msg += "   - Retrieving nuclei...\n"

	# Estimate background
	dna_bg = imt.estimate_background(im, imbin, seg_type)
	msg += "    > Estimated background: %.2f a.u.\n" % (dna_bg,)

	# Filter object size
	imbin, tmp = binarization.filter_obj_XY_size(imbin)
	imbin, tmp = binarization.filter_obj_Z_size(imbin)

	# Save default mask
	msg += "   - Saving default binary mask...\n"
	outname = "%smask.%s.default.png" % (maskdir, impath)
	save_mask_png(outname, imbin, impath, "Default mask.")

	# Export dilated mask
	if not noplot and 0 != dilate_factor:
		msg += "   - Saving dilated mask...\n"
		imbin_dil = dilation(imbin, cube(dilate_factor))
		title = "Dilated mask, %d factor." % (dilate_factor,)
		outname = "%smask.%s.dilated%d.png" % (maskdir, impath, dilate_factor)
		save_mask_png(outname, imbin_dil, impath, title)

	# Identify nuclei
	L = label(imbin)
	seq = range(1, L.max() + 1)

	# Save mask ----------------------------------------------------------------
	msg += "   - Saving nuclear ID mask...\n"
	title = 'Nuclei in "%s" [%d objects]' % (impath, im.max())
	outpath = "%smask.%s.nuclei.png" % (maskdir, impath)
	save_mask_png(outpath, L, impath, title)

	# Store nuclei -------------------------------------------------------------
	kwargs = {
		'series_id' : ii, 'thr' : thr,
		'dna_bg' : dna_bg, 'sig_bg' : 0,
		'aspect' : aspect, 'offset' : (1, 1, 1),
		'logpath' : logger.logpath, 'i' : im
	}

	curnuclei = []
	if 0 != dilate_factor:
		dilated_nmasks = {}
		msg += "   - Saving %d nuclei with dilation [%d]..." % (
			L.max(), dilate_factor)
		for n in seq:
			dilated_nmasks[n] = dilation(L == n, cube(dilate_factor))
			curnuclei.append(Nucleus(n = n, mask = dilated_nmasks[n], **kwargs))
			msg += "    > Applying nuclear box [%d]...\n" % (n,)
			dilated_nmasks[n] = imt.apply_box(
				dilated_nmasks[n], curnuclei[n - 1].box)
	else:
		msg += "   - Saving %d nuclei...\n" % (L.max(),)
		for n in seq:
			curnuclei.append(Nucleus(n = n, mask = L == n, **kwargs))
	nuclei.extend(curnuclei)

	# Assign dots to cells -----------------------------------------------------
	msg += "   - Analysis...\n"

	# Extract cell ID
	msg += "    > Assigning dots to cells...\n"
	subt = t.loc[subt_idx, :]
	if 0 == dilate_factor:
		# Add empty top/bottom slides
		imbin_tops = np.zeros((imbin.shape[0]+2, imbin.shape[1], imbin.shape[2]))
		imbin_tops[1:(imbin.shape[0]+1),:,:] = imbin

		L = label(imbin_tops)[1:(imbin.shape[0]+1),:,:]
		subt.loc[:, 'cell_ID'] = L[subt['z'], subt['x'], subt['y']]
	else:
		for idx in subt.index:
			coords = (
				subt.loc[idx, 'z'],
				subt.loc[idx, 'x'],
				subt.loc[idx, 'y']
			)
			for nid in range(1, len(curnuclei) + 1):
				if in_3d_box(curnuclei[nid - 1].box, coords):
					subt.loc[idx, 'cell_ID'] = nid
					break

	# Distances ----------------------------------------------------------------

	# Calculate distance from lamina
	msg += "    > Calculating lamina distance...\n"

	# Calculate distance and store it ------------------------------------------
	msg += "    > Calculating distances...\n"
	cell_max_lamin_dist = {0 : 1}
	if 0 == dilate_factor:
		D = distance_transform_edt(imbin_tops, aspect)[1:(imbin.shape[0]+1),:,:]
		subt.loc[:, 'lamin_dist'] = D[subt['z'], subt['x'], subt['y']]

		# Retrieve max lamin dist per cell
		for cid in range(subt['cell_ID'].max() + 1):
			cell_max_lamin_dist[cid] = np.max(D[np.where(L == cid)])
	else:
		for cid in range(1, int(subt['cell_ID'].max()) + 1):
			msg += "    >>> Working on cell #%d...\n" % (cid,)
			D = distance_transform_edt(dilated_nmasks[cid], aspect)
			cell_cond = cid == subt['cell_ID']
			bbox = curnuclei[cid - 1].box
			subt.loc[cell_cond, 'lamin_dist'] = D[
				subt.loc[cell_cond, 'z'] - bbox[0][0],
				subt.loc[cell_cond, 'x'] - bbox[1][0],
				subt.loc[cell_cond, 'y'] - bbox[2][0]]

			# Retrieve max lamin dist per cell
			cell_max_lamin_dist[cid] = D.max()

	# Normalize lamin_dist
	fnorm = [cell_max_lamin_dist[cid]
		for cid in subt['cell_ID'].tolist()]
	subt.loc[:, 'lamin_dist_norm'] = subt['lamin_dist'] / fnorm

	# Normalized centr_dist
	subt.loc[:, 'centr_dist_norm'] = 1 - subt['lamin_dist_norm']

	# Calculate centr_dist
	subt.loc[:, 'centr_dist'] = subt['centr_dist_norm'] * fnorm

	# Output
	print(msg)
	return((curnuclei, subt, subt_idx))

# RUN ==========================================================================

# Create output folder
if not os.path.isdir(outdir):
	os.mkdir(outdir)

# Create mask directory
maskdir = outdir + "masks/"
if not os.path.isdir(maskdir):
	os.mkdir(maskdir)

# Input ------------------------------------------------------------------------

# Read table
t = pd.read_csv(dot_table_name, delim)

# Add new empty columns
t['cell_ID'] = np.zeros(len(t.index))
t['lamin_dist'] = np.zeros(len(t.index))
t['lamin_dist_norm'] = np.zeros(len(t.index))
t['centr_dist'] = np.zeros(len(t.index))
t['centr_dist_norm'] = np.zeros(len(t.index))
t['dilation'] = dilate_factor

# Identify images --------------------------------------------------------------

# Extract FoV number
t['File'] = [int(f.split('/')[-1].split('.')[0]) for f in t['File']]

# Identify tiff images
flist = []
for (dirpath, dirnames, filenames) in os.walk(imdir):
    flist.extend(filenames)
    break
imlist = [f for f in flist if 'tif' in f]

# Assign field of views to images
imfov = {}
for i in set(t['File']):
	imfov[i] = [im for im in imlist if "%03d" % (i,) in im][0]

# Start iteration --------------------------------------------------------------

# Nuclei container
nuclei = []

# Cycle through
kwargs = {
	'imfov' : imfov, 'imdir' : imdir,
	'an_type' : an_type, 'seg_type' : seg_type, 'maskdir' : maskdir,
	'dilate_factor' : dilate_factor, 'aspect' : aspect, 't' : t
}
anData = Parallel(n_jobs = ncores)(
	delayed(analyze_field_of_view)(ii, **kwargs)
	for ii in range(len(imfov.keys())))
for (curnuclei, subt, subt_idx) in anData:
	nuclei.extend(curnuclei)
	t.loc[subt_idx, :] = subt

# Identify G1 cells ------------------------------------------------------------
if doSel:
	print("  - Flagging G1 cells...")

	# Retrieve nuclei summaries
	print('   > Retrieving nuclear summary...')
	summary = np.zeros(len(nuclei),
		dtype = gp.const.DTYPE_NUCLEAR_SUMMARY)
	for i in range(len(nuclei)):
		summary[i] = nuclei[i].get_summary()

	# Export summary
	outname = "%s/nuclei.out.dilate%d.%s" % (
		outdir, dilate_factor, dot_file_name)
	np.savetxt(outname, summary, delimiter = '\t')

	# Filter nuclei
	print('   > Filtering nuclei based on flatten size and intensity...')
	cond_name = 'none'
	sigma = .1
	nsf = (gp.const.NSEL_FLAT_SIZE, gp.const.NSEL_SUMI)
	out_dir = '.'

	# Filter features
	sel_data = {}
	plot_counter = 1
	for nsfi in nsf:
		# Identify Nuclear Selection Feature
		nsf_field = gp.const.NSEL_FIELDS[nsfi]
		nsf_name = gp.const.NSEL_NAMES[nsfi]
		print('   >> Filtering %s...' % (nsf_name,))

		# Start building output
		d = {'data' : summary[nsf_field]}

		# Calculate density
		d['density'] = stt.calc_density(d['data'], sigma = sigma)

		# Identify range
		args = [d['density']['x'], d['density']['y']]
		d['fwhm_range'] = stt.get_fwhm(*args)

		# Plot
		sel_data[nsf_field] = d

	# Select based on range
	f = lambda x, r: x >= r[0] and x <= r[1]
	for nsfi in nsf:
		nsf_field = gp.const.NSEL_FIELDS[nsfi]
		nsf_name = gp.const.NSEL_NAMES[nsfi]
		print("   > Selecting range for %s ..." % (nsf_name,))

		# Identify nuclei in the FWHM range
		nsf_data = sel_data[nsf_field]
		nsf_data['sel'] = [f(i, nsf_data['fwhm_range'])
			for i in nsf_data['data']]
		sel_data[nsf_field] = nsf_data
	
	# Select those in every FWHM range
	print("   > Applying selection criteria")
	nsfields = [gp.const.NSEL_FIELDS[nsfi] for nsfi in nsf]
	selected = [sel_data[f]['sel'] for f in nsfields]
	g = lambda i: all([sel[i] for sel in selected])
	selected = [i for i in range(len(selected[0])) if g(i)]
	sub_data = np.array(summary[selected])

	# Identify selected nuclei objects
	sel_nucl = []
	for n in nuclei:
		if n.n in sub_data['n'][np.where(n.s == sub_data['s'])[0]]:
			sel_nucl.append(n)

	# Check which dots are in which nucleus and update flag
	print("   > Matching DOTTER cells with GPSeq cells...")
	t['G1'] = np.zeros((t.shape[0],))
	for ti in t.index:
		for ni in range(len(sel_nucl)):
			n = sel_nucl[ni]
			if in_nucleus(n, int(t.ix[ti, 0]-1), tuple(t.ix[ti, [5, 3, 4]])):
				t.ix[ti, 'G1'] = 1
				break

# Add allele information -------------------------------------------------------
print("  - Adding allele information...")
t = add_allele(t)

# Write output -----------------------------------------------------------------
outname = "%s/wCentr.out.dilate%d.%s" % (outdir, dilate_factor, dot_file_name)
t.to_csv(outname, sep = '\t', index = False)

# END ==========================================================================

################################################################################
