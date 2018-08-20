pyGPSeq v3.2.1
===

A Python3 package that provides tools to analyze images of GPSeq samples.

* Read the (public) [documentation](https://ggirelli.github.io/pygpseq/) for more details.
* Read the (private) [documentation](https://github.com/ggirelli/pygpseq/wiki) for more details.  
*Once the repo goes public, private docs will be merged with public ones.*

Installation
-------------

To **install**, run the following:

```
git clone http://github.com/ggirelli/pygpseq
cd pygpseq
sudo -H pip3 install .
```

To **uninstall** run the following from within the repository folder:

```
sudo -H pip3 uninstall pygpseq
```

To **update**, first uninstall, and then run the following from within the repository folder.

```
git pull
sudo -H pip3 install .
```

Usage
----------

#### Analyze a GPSeq image dataset

The `gpseq_anim` (**GPSeq** **an**alysis of **im**ages) analyzes a multi-condition GPSeq image dataset. Run `gpseq_anim -h` for more details.

#### Calculate lamin distance of FISH signals

The `gpseq_fromfish` script characterizes FISH signals identified with `DOTTER` (or similar tools) by calculating: absolute/normalized distance from lamina and central region, nuclear compartment, allele status,... Run `gpseq_fromfish -h` for more details.

#### Merge multiple FISH analyses using a metadata table

Use the `gpseq_fromfish_merge` script to merge multiple FISH analysis output (generated with `gpseq_fromfish`). For more details run `gpseq_fromfish_merge -h`.

#### Perform automatic 3D nuclei segmentation

Run `tiff_auto3dseg -h` for more details on how to produce binary/labeled (compressed) masks of your nuclei staining channels

#### Identify out of focus (OOF) fields of view

Run `tiff_findoof -h` for more details on how to quickly identify out of focus fields of view. Also, the `tiff_plotoof` script (in R, requires `argparser` and `ggplot2`) can be used to produce an informative plot with the signal location over the Z stack.

#### Split a tiff in smaller images

To split a large tiff to smaller square images of size N x N pixels, run `tiff_split input_image output_folder N`. Use the `--enlarge` option to avoid pixel loss. If the input image is a 3D stack, then the output images will be of N x N x N voxels, use the `--2d` to apply the split only to the first slice of the stack. For more details, run `tiff_split -h`.

#### (Un)compress a tiff

To uncompress a set of tiff, use the `tiffcu -u` command. To compress them use the `tiffcu -c` command instead. Use `tiffcu -h` for more details.

#### Convert a nd2 file into single-channel tiff images

Use the `nd2_to_tiff` tool to convert images bundled into a nd2 file into separate single-channel tiff images. Use `nd2_to_tiff -h` for the documentation.

Contributing
---

We welcome any contributions to `pygpseq`. Please, refer to the [contribution guidelines](https://ggirelli.github.io/pygpseq/contributing) if this is your first time contributing! Also, check out our [code of conduct](https://ggirelli.github.io/pygpseq/code_of_conduct).

License
---

```
MIT License
Copyright (c) 2017 Gabriele Girelli
```