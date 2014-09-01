import vigra
import os
import h5py
import ilp_constants as const


def eval_h5(proj, key_list):
    """Recursively apply the keys in key_list to proj.

    Example: If key_list is ["key1", "key2"], then proj["key1"]["key2"] is returned.
    :param proj: h5py File object
    :param key_list: list of keys to be applied to proj
    :return: entry of the last dict after all keys have been applied
    """
    if not isinstance(proj, h5py.File):
        raise Exception("A valid h5py File object must be given.")
    val = proj
    for key in key_list:
        val = val[key]
    return val


def reshape_txyzc(data):
    """Reshape data to txyzc and set proper axistags.

    :param data: dataset to be reshaped
    :type data: vigra or numpy array
    :return: reshaped dataset
    """
    if not hasattr(data, "axistags"):
        axistags = vigra.defaultAxistags(len(data.shape))
    else:
        axistags = data.axistags

    # Get the axes that have to be added to the dataset.
    axes = {"t": vigra.AxisInfo.t,
            "x": vigra.AxisInfo.x,
            "y": vigra.AxisInfo.y,
            "z": vigra.AxisInfo.z,
            "c": vigra.AxisInfo.c}
    for axis in axistags:
        assert isinstance(axis, vigra.AxisInfo)
        axes.pop(axis.key, None)  # Remove ax from the dict.

    # Add the axes and create the new shape.
    data_shape = list(data.shape)
    for axis in axes.values():
        axistags.append(axis)
        data_shape.append(1)
    data_shape = tuple(data_shape)

    # Reshape the old data and apply the new axistags.
    return data.reshape(data_shape, axistags=axistags)


# TODO:
# Use joblib to cache the accesses of the h5 project file.
# https://pythonhosted.org/joblib/memory.html
class ILP(object):
    """Provides basic interactions with ilp files.
    """

    @property
    def project_filename(self):
        """Returns filename of the ilp project.

        :return: filename of the ilp project
        """
        return self._project_filename

    @property
    def project_dir(self):
        """Returns directory path of the project file.

        :return: directory path of project file
        """
        return os.path.dirname(os.path.realpath(self.project_filename))

    @property
    def cache_folder(self):
        """Returns path of the cache folder.

        :return: path of the cache folder
        """
        return self._cache_folder

    def __init__(self, project_filename, output_folder):
        self._project_filename = project_filename
        self._cache_folder = output_folder
        if not os.path.exists(output_folder):
            os.makedirs(output_folder)
        # TODO:
        # Maybe check if the project exists and can be opened.

    def get_data_count(self):
        """Returns the number of datasets inside the project file.
        :return: number of datasets
        """
        proj = h5py.File(self.project_filename, "r")
        input_infos = eval_h5(proj, const.input_infos_list())
        data_count = len(input_infos.keys())
        proj.close()
        return data_count

    def get_data_path(self, data_nr):
        """Returns the file path of the dataset.

        :param data_nr: number of dataset
        :return: file path of the dataset
        """
        h5_key = const.filepath(data_nr)
        data_path = vigra.readHDF5(self.project_filename, h5_key)
        data_key = os.path.basename(data_path)
        data_path = os.path.join(self.project_dir, data_path[:-len(data_key)-1])
        return data_path

    def get_data_key(self, data_nr):
        """Returns the h5 key of the dataset.

        :param data_nr: number of dataset
        :return: key of the dataset inside its h5 file
        """
        h5_key = const.filepath(data_nr)
        data_path = vigra.readHDF5(self.project_filename, h5_key)
        data_key = os.path.basename(data_path)
        return data_key

    def get_data(self, data_nr):
        """Returns the dataset.

        :param data_nr: number of dataset
        :return: the dataset
        """
        return vigra.readHDF5(self.get_data_path(data_nr), self.get_data_key(data_nr))

    def get_output_data_path(self, data_nr):
        """Returns the file path to the probability data of the dataset.

        :param data_nr: number of dataset
        :return: file path to probability data of the dataset
        """
        data_path = self.get_data_path(data_nr)
        filename, ext = os.path.splitext(os.path.basename(data_path))
        return filename + "_probs" + ext

    def get_axisorder(self, data_nr):
        """Returns the axisorder of the dataset.

        :param data_nr: number of dataset
        :return: axisorder of dataset
        """
        return vigra.readHDF5(self.project_filename, const.axisorder(data_nr))

    @staticmethod
    def _h5_labels(proj, data_nr):
        """Returns the h5py object that holds the label blocks.

        :param proj: the ilp project file
        :type proj: h5py.File
        :param data_nr: number of dataset
        :return: labels of the dataset as h5py object
        """
        if not isinstance(proj, h5py.File):
            raise Exception("A valid h5py File object must be given.")
        data_nr = str(data_nr).zfill(3)
        h5_key = const.labels_list(data_nr)
        return eval_h5(proj, h5_key)

    def _label_block_count(self, data_nr):
        """Returns the number of label blocks of the dataset.

        :param data_nr: number of dataset
        :return: number of label blocks of the dataset
        """
        proj = h5py.File(self.project_filename, "r")
        labels = ILP._h5_labels(proj, data_nr)
        block_count = len(labels.keys())
        proj.close()
        return block_count

    def get_labels(self, data_nr):
        """Returns the labels and their block slices of the dataset.

        :param data_nr: number of dataset
        :return: labels and blockslices of the dataset
        """
        # Read the label blocks.
        block_count = self._label_block_count(data_nr)
        blocks = [vigra.readHDF5(self.project_filename, const.label_blocks(data_nr, i))
                  for i in range(block_count)]

        # Read the block slices.
        proj = h5py.File(self.project_filename, "r")
        block_slices = [eval_h5(proj, const.label_blocks_list(data_nr, i)).attrs['blockSlice']
                        for i in range(block_count)]
        proj.close()
        return blocks, block_slices

    def replace_labels(self, data_nr, blocks, block_slices):
        """Replaces the labels and their block slices of the dataset.

        :param data_nr: number of dataset
        :param blocks: label blocks
        :param block_slices: block slices
        """
        if len(blocks) != self._label_block_count(data_nr):
            raise Exception("Wrong number of label blocks to be inserted.")
        if len(block_slices) != self._label_block_count(data_nr):
            raise Exception("Wrong number of label block slices to be inserted.")

        proj = h5py.File(self.project_filename, "r+")
        for i in range(self._label_block_count(data_nr)):
            vigra.writeHDF5(blocks[i], self.project_filename, const.label_blocks(data_nr, i))
            h5_blocks = eval_h5(proj, const.label_blocks_list(data_nr, i))
            h5_blocks.attrs['blockSlice'] = block_slices[i]
        proj.close()

    # TODO: Update docstring (return).
    def extend_data_txyzc(self, data_nr=None):
        """Extend the dimension of some dataset and its labels to txyzc.

        If data_nr is None, all datasets are extended.
        :param data_nr: number of dataset
        :return:
        """
        if data_nr is None:
            for i in range(self.get_data_count()):
                self.extend_data_txyzc(i)
        else:
            # Reshape the data with the correct axistags.
            data = self.get_data(data_nr)
            axisorder = self.get_axisorder(data_nr)
            if not hasattr(data, "axistags"):
                data = vigra.VigraArray(data, axistags=vigra.defaultAxistags(axisorder))
            new_data = reshape_txyzc(data)

            print self.get_output_data_path(data_nr)

            # TODO:
            # Save new_data in the output folder.
            # Update the project file: Use new_data, set axisorder, set axistags.
            # Reshape the labels to txyzc and update label's blockSlices attribute.

    # TODO: Implement this function.
    def retrain(self, ilastik_cmd):
        """Retrain the project using ilastik.

        :param ilastik_cmd: path to the file run_ilastik.sh
        :return:
        """
        return

    # TODO: Implement this function.
    def merge_probs_into_raw(self, data_nr, probs_filename=None):
        """Merge probabilities into raw data.

        If probs_filename is None, the default output of retrain is taken.
        :param data_nr:
        :param probs_filename:
        :return:
        """
        return
