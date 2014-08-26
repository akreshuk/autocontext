# labels.py
#
# Functions to modify labels.
import numpy
import math
import random


# Randomly scatter the labels of a single label block into several layers.
def scatter_labels_single_block(label_block, label_count, n):
    # Find the label coordinates inside the block.
    wh_list = [numpy.where(label_block == i+1) for i in range(label_count)]
    available_list = [range(len(wh[0])) for wh in wh_list]

    scatter_blocks = []
    for k in range(n):
        block = numpy.zeros(label_block.shape, dtype=label_block.dtype)
        for i in range(label_count):
            # Choose a random sample of the available indices.
            available_indices = available_list[i]
            num_samples = int(math.ceil(float(len(available_indices))/(n-k)))
            chosen_indices = random.sample(available_indices, num_samples)

            # Remove the chosen indices from the available indices.
            available_list[i] = [x for x in available_indices if x not in chosen_indices]

            # Take the coordinates of the chosen indices in the block and put the current label there.
            wh = tuple(w[chosen_indices] for w in wh_list[i])
            block[wh] = i+1
        scatter_blocks.append(block)
    return scatter_blocks


# Randomly scatter the labels of label blocks into several layers.
# label_blocks: List of label blocks.
# n: Number of splits.
#
# Returns:
# List, where each item is of the same format as label_blocks,
# containing only an n-th of the original labels.
def scatter_labels(label_blocks, label_count, n):
    return_list = [[] for __ in range(n)]
    for block in label_blocks:
        scatter_blocks = scatter_labels_single_block(block, label_count, n)
        for i, b in enumerate(scatter_blocks):
            return_list[i].append(b)
    return return_list
