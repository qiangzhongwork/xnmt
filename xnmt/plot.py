import numpy as np
import matplotlib
matplotlib.use('Agg')

import matplotlib.pyplot as plt

from xnmt import util

def plot_attention(src_words, trg_words, attention_matrix, file_name=None, size_x = 8.0, size_y = 8.0):
  """This takes in source and target words and an attention matrix (in numpy format)
  and prints a visualization of this to a file.

  Args:
    src_words: a list of words in the source
    trg_words: a list of target words
    attention_matrix: a two-dimensional numpy array of values between zero and one,
      where rows correspond to source words, and columns correspond to target words
    file_name: the name of the file to which we write the attention
  """
  if len(''.join(src_words))>100 or len(''.join(trg_words))>100: matplotlib.rc('font', size=4)
  if len(''.join(src_words))>50 or len(''.join(trg_words))>50: matplotlib.rc('font', size=7)
  fig, ax = plt.subplots(figsize=(size_x, size_y))
  # put the major ticks at the middle of each cell
  ax.set_xticks(np.arange(attention_matrix.shape[1]) + 0.5, minor=False)
  ax.set_yticks(np.arange(attention_matrix.shape[0]) + 0.5, minor=False)
  ax.invert_yaxis()
  if not src_words: plt.yticks([], [])

  # label axes by words
  ax.set_xticklabels(trg_words, minor=False)
  ax.set_yticklabels(src_words, minor=False)
  ax.xaxis.tick_top()

  # draw the heatmap
  plt.pcolor(attention_matrix, cmap=plt.cm.Blues, vmin=0, vmax=1)
  plt.colorbar()

  if file_name is not None:
    util.make_parent_dir(file_name)
    plt.savefig(file_name, dpi=100)
  else:
    plt.show()
  plt.close()

def plot_speech_features(feature_matrix, file_name=None, vertical = True, length = 8.0):
  """Plot speech feature matrix.

  Args:
    feature_matrix: a two-dimensional numpy array of values between zero and one,
      where rows correspond to source words, and columns correspond to target words
    file_name: the name of the file to which we write the attention
  """
  plt.subplots(figsize=(1.0, length))
  if vertical: feature_matrix = feature_matrix.T
  plt.pcolor(feature_matrix, cmap=plt.cm.coolwarm, vmin=0, vmax=1)
  plt.axis('off')
  if file_name is not None:
    util.make_parent_dir(file_name)
    plt.savefig(file_name, dpi=100)
  else:
    plt.show()
  plt.close()
