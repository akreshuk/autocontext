"""
DESCRIPTION

How to use:
* Start a new ilastik pixel classification project and add one or more datasets.
* Select some features.
* Add some labels.
* Save project and exit ilastik.
* Run this script (parameters: see command line arguments from argparse) or use the autocontext function.
"""
import argparse
import os
import random
import shutil
import subprocess
import sys

import colorama as col
import vigra

from core.ilp import ILP
from core.ilp import merge_datasets, reshape_tzyxc
from core.labels import scatter_labels
from core.ilp_constants import default_export_key


def autocontext(ilastik_cmd, project, runs, label_data_nr, weights=None, predict_file=False):
    """Trains and predicts the ilastik project using the autocontext method.

    The parameter weights can be used to take different amounts of the labels in each loop run.
    Example: runs = 3, weights = [3, 2, 1]
             The sum of the weights is 6, so in the first run, 1/2 (== 3/6) of the labels is used,
             then 1/3 (== 2/6), then 1/6.
    If weights is None, the labels are equally distributed over the loop runs.
    :param ilastik_cmd: path to run_ilastik.sh
    :param project: the ILP object of the project
    :param runs: number of runs of the autocontet loop
    :param label_data_nr: number of dataset that contains the labels (-1: use all datasets)
    :param weights: weights for the labels
    :param predict_file: if this is True, the --predict_file option of ilastik is used
    """
    assert isinstance(project, ILP)

    # Create weights if none were given.
    if weights is None:
        weights = [1]*runs
    if len(weights) < runs:
        raise Exception("The number of weights must not be smaller than the number of runs.")
    weights = weights[:runs]

    # Copy the raw data to the output folder and reshape it to txyzc.
    project.extend_data_tzyxc()

    # Get the number of datasets.
    data_count = project.data_count

    # Get the current number of channels in the datasets.
    # The data in those channels is left unchanged when the ilastik output is merged back.
    keep_channels = [project.get_channel_count(i) for i in range(data_count)]

    # Read the labels from the first block and split them into parts, so not all labels are used in each loop.
    label_count = len(project.label_names)
    if label_data_nr == -1:
        blocks_with_slicing = [(i, project.get_labels(i)) for i in xrange(project.labelsets_count)]
    else:
        blocks_with_slicing = [(label_data_nr, project.get_labels(label_data_nr))]
    scattered_labels_list = [scatter_labels(blocks, label_count, runs, weights)
                             for i, (blocks, block_slices) in blocks_with_slicing]

    # Do the autocontext loop.
    for i in range(runs):
        print col.Fore.GREEN + "- Running autocontext training round %d of %d -" % (i+1, runs) + col.Fore.RESET

        # Insert the subset of the labels into the project.
        for (k, (blocks, block_slices)), scattered_labels in zip(blocks_with_slicing, scattered_labels_list):
            split_blocks = scattered_labels[i]
            project.replace_labels(k, split_blocks, block_slices)

        # Retrain the project.
        print col.Fore.GREEN + "Retraining:" + col.Fore.RESET
        project.retrain(ilastik_cmd)

        # Save the project so it can be used in the batch prediction.
        filename = "rf_" + str(i).zfill(len(str(runs-1))) + ".ilp"
        filename = os.path.join(project.cache_folder, filename)
        print col.Fore.GREEN + "Saving the project to " + filename + col.Fore.RESET
        project.save(filename, remove_labels=True)

        # Predict all datasets.
        print col.Fore.GREEN + "Predicting all datasets:" + col.Fore.RESET
        project.predict_all_datasets(ilastik_cmd, predict_file=predict_file)

        # Merge the probabilities back into the datasets.
        print col.Fore.GREEN + "Merging output back into datasets." + col.Fore.RESET
        for k in range(data_count):
            project.merge_output_into_dataset(k, keep_channels[k])

    # Insert the original labels back into the project.
    for k, (blocks, block_slices) in blocks_with_slicing:
        project.replace_labels(k, blocks, block_slices)


def autocontext_forests(dirname):
    """Open the ilastik random forests from the given trained autocontext.

    :param dirname: autocontext cache folder
    :return: list with ilastik random forest filenames
    """
    rf_files = []
    for filename in os.listdir(dirname):
        fullname = os.path.join(dirname, filename)
        if os.path.isfile(fullname) and len(filename) >= 8:
            base, middle, end = filename[:3], filename[3:-4], filename[-4:]
            if base == "rf_" and end ==".ilp":
                rf_files.append((int(middle), fullname))
    rf_files = sorted(rf_files)
    rf_indices, rf_files = zip(*rf_files)
    assert rf_indices == tuple(xrange(len(rf_files)))  # check that there are only the indices 0, 1, 2, ... .
    return rf_files


def batch_predict(args, ilastik_args):
    """Do the batch prediction.

    :param args: command line arguments
    :param ilastik_args: additional ilastik arguments
    """
    # Create the folder for the intermediate results.
    if not os.path.isdir(args.cache):
        os.makedirs(args.cache)

    # Find the random forest files.
    rf_files = autocontext_forests(args.batch_predict)
    n = len(rf_files)

    # Get the output format arguments.
    default_output_format = "hdf5"
    default_output_filename_format = os.path.join(args.cache, "{nickname}_probs.h5")
    ilastik_parser = argparse.ArgumentParser()
    ilastik_parser.add_argument("--output_format", type=str, default=default_output_format)
    ilastik_parser.add_argument("--output_filename_format", type=str, default=default_output_filename_format)
    format_args, ilastik_args = ilastik_parser.parse_known_args(ilastik_args)
    output_formats = [default_output_format] * (n-1) + [format_args.output_format]
    output_filename_formats = [default_output_filename_format] * (n-1) + [format_args.output_filename_format]

    # Reshape the data to tzyxc and move it to the cache folder.
    outfiles = []
    keep_channels = None
    for i in xrange(len(args.files)):
        # Read the data and attach axistags.
        filename = args.files[i]
        data_key = os.path.basename(filename)
        data_path = filename[:-len(data_key)-1]
        data = vigra.readHDF5(data_path, data_key)
        if not hasattr(data, "axistags"):
            default_tags = {1: "x",
                            2: "xy",
                            3: "xyz",
                            4: "xyzc",
                            5: "txyzc"}
            data = vigra.VigraArray(data, axistags=vigra.defaultAxistags(default_tags[len(data.shape)]),
                                    dtype=data.dtype)
        new_data = reshape_tzyxc(data)
        if i == 0:
            keep_channels = new_data.shape[-1]

        # Save the reshaped dataset.
        output_filename = os.path.split(data_path)[1]
        output_filename = os.path.join(args.cache, output_filename)
        vigra.writeHDF5(new_data, output_filename, data_key, compression=args.compression)
        args.files[i] = output_filename + "/" + data_key
        outfiles.append(os.path.splitext(output_filename)[0] + "_probs.h5")
    assert keep_channels > 0

    # Run the batch prediction.
    for i in xrange(n):
        rf_file = rf_files[i]
        output_format = output_formats[i]
        output_filename_format = output_filename_formats[i]

        filename_key = os.path.basename(args.files[0])
        filename_path = args.files[0][:-len(filename_key)-1]

        # Quick hack to prevent the ilastik error "wrong number of channels".
        p = ILP(rf_file, args.cache, compression=args.compression)
        p.set_data_path_key(0, filename_path, filename_key)

        # Call ilastik to run the batch prediction.
        cmd = [args.ilastik,
               "--headless",
               "--project=%s" % rf_file,
               "--output_format=%s" % output_format,
               "--output_filename_format=%s" % output_filename_format]
        cmd += args.files
        print col.Fore.GREEN + "- Running autocontext batch prediction round %d of %d -" % (i+1, n) + col.Fore.RESET
        subprocess.call(cmd, stdout=sys.stdout)

        # Merge the probabilities back to the original file.
        for filename, filename_out in zip(args.files, outfiles):
            filename_key = os.path.basename(filename)
            filename_path = filename[:-len(filename_key)-1]
            merge_datasets(filename_path, filename_key, filename_out, default_export_key(), n=keep_channels,
                           compression=args.compression)


def train(args):
    """Do the autocontext training.

    :param args: command line arguments
    """
    # Copy the project file.
    # TODO: If the file exists, ask the user if it shall be deleted.
    if os.path.isfile(args.outfile):
        os.remove(args.outfile)
    shutil.copyfile(args.train, args.outfile)

    # Create an ILP object for the project.
    proj = ILP(args.outfile, args.cache, args.compression)

    # Do the autocontext loop.
    autocontext(args.ilastik, proj, args.nloops, args.labeldataset, predict_file=args.predict_file)


def process_command_line():
    """Parse command line arguments.
    """
    # Add the command line arguments.
    parser = argparse.ArgumentParser(description="ilastik autocontext",
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    # Ilastik arguments.
    parser.add_argument("--ilastik", type=str, required=True,
                        help="path to the file run_ilastik.sh")

    # Training arguments.
    parser.add_argument("--train", type=str,
                        help="path to the ilastik project that will be used for training")
    parser.add_argument("-o", "--outfile", type=str, default="",
                        help="output file")
    parser.add_argument("-n", "--nloops", type=int, default=3,
                        help="number of autocontext loop iterations")
    parser.add_argument("-d", "--labeldataset", type=int, default=-1,
                        help="id of dataset in the ilp file that contains the labels (-1: use all datasets)")
    parser.add_argument("-c", "--cache", type=str, default="cache",
                        help="name of the cache folder")
    parser.add_argument("--seed", type=int, default=None,
                        help="the random seed")
    parser.add_argument("--predict_file", action="store_true",
                        help="add this flag if ilastik supports the --predict_file option")
    parser.add_argument("--compression", default="lzf", type=str, choices=["lzf", "gzip", "szip", "None"],
                        help="compression filter for the hdf5 files")

    # Batch prediction arguments.
    parser.add_argument("--batch_predict", type=str,
                        help="path of the cache folder of a previously trained autocontext that will be used for batch "
                             "prediction")
    parser.add_argument("--files", type=str, nargs="+",
                        help="the files for the batch prediction")

    # Do the parsing.
    args, ilastik_args = parser.parse_known_args()

    # Check if ilastik is an executable.
    if not os.path.isfile(args.ilastik) or not os.access(args.ilastik, os.X_OK):
        raise Exception("%s is not an executable file." % args.ilastik)

    # Check for conflicts between training and batch prediction arguments.
    if args.train is None and args.batch_predict is None:
        raise Exception("One of the arguments --train or --batch_predict must be given.")
    if args.train is not None and args.batch_predict is not None:
        raise Exception("--train and --batch_predict must not be combined.")

    # Check if the training arguments are valid.
    if args.train:
        if len(ilastik_args) > 0:
            raise Exception("The training does not accept unknown arguments: %s" % ilastik_args)
        if args.files is not None:
            raise Exception("--train cannot be used for batch prediction.")
        if not os.path.isfile(args.train):
            raise Exception("%s is not a file." % args.train)
        if len(args.outfile) == 0:
            file_path, file_ext = os.path.splitext(args.train)
            args.outfile = file_path + "_out" + file_ext
        if args.labeldataset < -1:
            raise Exception("Wrong id of label dataset: %d" % args.d)
        if args.compression == "None":
            args.compression = None

    # Check if the batch prediction arguments are valid.
    if args.batch_predict:
        if args.files is None:
            raise Exception("Tried to use batch prediction without --files.")
        if not os.path.isdir(args.batch_predict):
            raise Exception("%s is not a directory." % args.batch_predict)

        # Remove the --headless, --project and --output_internal_path arguments.
        ilastik_parser = argparse.ArgumentParser()
        ilastik_parser.add_argument("--headless", action="store_true")
        ilastik_parser.add_argument("--project", type=str)
        ilastik_parser.add_argument("--output_internal_path", type=str)
        ilastik_args = ilastik_parser.parse_known_args(ilastik_args)[1]

    return args, ilastik_args


def main():
    """
    """

    # Read command line arguments.
    args, ilastik_args = process_command_line()

    # Initialize colorama and random seeds.
    random.seed(args.seed)
    col.init()

    # Clear the cache folder.
    if os.path.isdir(args.cache):
        print "The cache folder", os.path.abspath(args.cache), "already exists."
        clear_cache = raw_input("Clear cache folder? [y|n] : ")
        if clear_cache in ["y", "Y"]:
            for f in os.listdir(args.cache):
                f_path = os.path.join(args.cache, f)
                try:
                    if os.path.isfile(f_path):
                        os.remove(f_path)
                    elif os.path.isdir(f_path):
                        shutil.rmtree(f_path)
                except Exception, e:
                    print e
            print "Cleared cache folder."
        else:
            print "Cache folder not cleared."

    if args.train:
        # Do the autocontext training.
        train(args)
    else:
        # Do the batch prediction.
        assert args.batch_predict
        batch_predict(args, ilastik_args)

    return 0


if __name__ == "__main__":
    status = main()
    sys.exit(status)
