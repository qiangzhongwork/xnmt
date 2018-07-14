"""
Reports gather inputs, outputs, intermediate computations in a nicely formatted way for convenient manual inspection.

To support reporting, the models providing the data to be reported must subclass ``Reportable`` and call
self.add_sent_for_report(d) with key/value pairs containing the data to be reported at the appropriate times.
If this causes a computation overhead, the boolean ``compute_report`` field should used and extra computations skipped
unless this field is ``True``.

Next, a reporter needs to be specified that supports reports based on the previously created key/value pairs.
Reporters are assigned to inference classes, so it's possible to report only at the final test decoding, or specify
a special reporting inference object that only looks at a handful of sentences, etc.

Note that currently reporting is only supported at test-time, not at training time.
"""

import os
from lxml import etree
from typing import Any, Dict, Optional, Tuple
import numpy as np
from xml.sax.saxutils import escape

from xnmt.events import register_xnmt_event_assign, handle_xnmt_event, register_xnmt_handler
import xnmt.plot
from xnmt.persistence import Serializable, serializable_init
from xnmt import vocab, util
import xnmt.output
from xnmt.settings import settings

class Reportable(object):
  """
  Base class for classes that contribute information to a report.

  Doing so requires the implementing class to do the following:

  - specify Reportable as base class
  - call this super class's __init__(), or do @register_xnmt_handler manually
  - call self.add_sent_for_report(d) for each sentence, where d is a dictionary containing info to pass on to the
    reporter
  """

  @register_xnmt_handler
  def __init__(self) -> None:
    self._sent_info_list = []

  def add_sent_for_report(self, sent_info: Dict[str,Any]) -> None:
    """
    Add key/value pairs belonging to the current sentence for reporting.

    This should be called consistently for every sentence and in order.

    Args:
      sent_info: A dictionary of key/value pairs. The keys must match (be a subset of) the arguments in the reporter's
                 create_report() method, and the values must be of the corresponding types.
    """
    if not hasattr(self, "_sent_info_list"):
      self._sent_info_list = []
    self._sent_info_list.append(sent_info)

  @handle_xnmt_event
  def on_get_report_input(self, context={}):
    if not hasattr(self, "_sent_info_list"):
      return context
    if len(context)>0:
      assert len(context) == len(self._sent_info_list)
    else:
      context = []
      for _ in range(len(self._sent_info_list)): context.append({})
    for context_i, sent_i in zip(context, self._sent_info_list):
      context_i.update(sent_i)
    self._sent_info_list.clear()
    return context

class Reporter(object):
  """
  A base class for a reporter that collects reportable information, formats it and writes it to disk.
  """
  def create_report(self, **kwargs) -> None:
    """
    Create the report.

    The reporter should specify the arguments it needs explicitly, and should specify kwargs in addition to handle extra
    (unused) arguments without crashing.

    Args:
      **kwargs: additional arguments
    """
    raise NotImplementedError("must be implemented by subclasses")
  @register_xnmt_event_assign
  def get_report_input(self, context={}) -> dict:
    return context

class CharCutReporter(Reporter, Serializable):
  """
  Reporter that uses the CharCut tool for nicely displayed difference highlighting between outputs and references.

  The stand-alone tool can be found at https://github.com/alardill/CharCut

  Args:
    match_size: min match size in characters (set < 3 e.g. for Japanese or Chinese)
    alt_norm: alternative normalization scheme: use only the candidate's length for normalization
  """
  yaml_tag = "!CharCutReporter"
  @serializable_init
  @register_xnmt_handler
  def __init__(self, match_size: int = 3, alt_norm: bool = False, report_path: str = settings.DEFAULT_REPORT_PREFIX) \
          -> None:
    self.match_size = match_size
    self.alt_norm = alt_norm
    self.report_path = report_path
    self.hyp_sents, self.ref_sents, self.src_sents = [], [], []

  def create_report(self, src: xnmt.input.Input, src_vocab: vocab.Vocab, trg_vocab: vocab.Vocab,
                    output: xnmt.output.Output, output_proc: xnmt.output.OutputProcessor,
                    reference: Optional[str] = None, **kwargs) -> None:
    trg_str = output.apply_post_processor(output_proc)
    src_is_speech = isinstance(src, xnmt.input.ArrayInput)
    if not src_is_speech:
      src_str = " ".join([src_vocab.i2w[src_token] for src_token in src])
      self.src_sents.append(src_str)
    self.hyp_sents.append(trg_str)
    self.ref_sents.append(reference)

  @handle_xnmt_event
  def on_end_inference(self):
    class ArgClass(object):
      def __init__(self, **kwargs):
        for key in kwargs: setattr(self, key, kwargs[key])
    if self.hyp_sents:
      hyp_filename = f"{self.report_path}.charcut.tmp_c"
      ref_filename = f"{self.report_path}.charcut.tmp_r"
      src_filename = f"{self.report_path}.charcut.tmp_s"
      html_filename = f"{self.report_path}.charcut.html"
      util.make_parent_dir(hyp_filename)
      with open(hyp_filename, "w") as fout:
        fout.write("\n".join(self.hyp_sents))
      with open(ref_filename, "w") as fout:
        fout.write("\n".join(self.ref_sents))
      if self.src_sents:
        with open(src_filename, "w") as fout:
          fout.write("\n".join(self.src_sents))
      import xnmt.thirdparty.charcut_py3.charcut as charcut
      args = ArgClass(cand=hyp_filename, ref=ref_filename, html_output_file=html_filename, match_size=self.match_size,
                      alt_norm=self.alt_norm, src=src_filename if self.src_sents else None)
      aligned_segs = charcut.load_input_files(args)
      charcut.run_on(aligned_segs, args)
      self.hyp_sents, self.ref_sents, self.src_sents = [], [], []

class HtmlReporter(Reporter):
  """
  A base class for reporters that produce HTML outputs that takes care of some common functionality.

  Args:
    report_path: Prefix for path to write HTML and image files to (i.e. directory + filename-prefix)
  """
  def __init__(self, report_path: str = settings.DEFAULT_REPORT_PREFIX) -> None:
    self.report_path = report_path
    self.html_tree = etree.Element('html')
    meta = etree.SubElement(self.html_tree, 'meta')
    meta.attrib['charset'] = 'UTF-8'
    head = etree.SubElement(self.html_tree, 'head')
    title = etree.SubElement(head, 'title')
    title.text = 'Translation Report'
    self.html_body = etree.SubElement(self.html_tree, 'body')

  def start_sent(self, idx: int) :
    report_div = etree.SubElement(self.html_body, 'div')
    report = etree.SubElement(report_div, 'h1')
    report.text = f'Translation Report for Sentence {idx}'
    main_content = etree.SubElement(report_div, 'div', name='main_content')
    return main_content

  def write_html_tree(self) -> None:
    html_str = etree.tostring(self.html_tree, encoding='unicode', pretty_print=True)
    html_file_name = self.report_path + '.html'
    util.make_parent_dir(html_file_name)
    with open(html_file_name, 'w', encoding='utf-8') as f:
      f.write(html_str)

  def add_sent_in_out(self, main_content, output, output_proc: xnmt.output.OutputProcessor, src, src_vocab,
                      reference: Optional[str]=None) -> Tuple[str, str]:
    src_is_speech = isinstance(src, xnmt.input.ArrayInput)
    if src_is_speech:
      src_str = ""
    else:
      src_str = " ".join([src_vocab.i2w[src_token] for src_token in src])
    trg_str = output.apply_post_processor(output_proc)
    captions, inputs = [], []
    if not src_is_speech:
      captions.append("Source Words")
      inputs.append(src_str)
    captions.append("Output Words")
    inputs.append(trg_str)
    if reference:
      captions.append("Reference Words")
      inputs.append(reference)
    for caption, sent in zip(captions, inputs):
      p = etree.SubElement(main_content, 'p')
      b = etree.SubElement(p, 'b')
      c = etree.SubElement(p, 'span')
      b.text = f"{caption}: "
      c.text = sent
    return src_str, trg_str


class AttentionHtmlReporter(HtmlReporter, Serializable):
  """
  Reporter that writes attention matrices to HTML.

  Args:
    report_path: Prefix for path to write HTML and image files to (i.e. directory + filename-prefix)
  """

  yaml_tag = "!AttentionHtmlReporter"

  @serializable_init
  def __init__(self, report_path: str = settings.DEFAULT_REPORT_PREFIX):
    super().__init__(report_path=report_path)

  def create_report(self, idx: int, src: xnmt.input.Input, src_vocab: vocab.Vocab,
                    trg_vocab: vocab.Vocab, output: xnmt.output.Output, output_proc: xnmt.output.OutputProcessor,
                    attentions: np.ndarray, reference: Optional[str] = None, **kwargs) -> None:
    """
    Create report.

    Args:
      idx: number of sentence
      src: source-side input
      src_vocab: source-side vocabulary
      trg_vocab: source-side vocabulary
      output: generated output
      attentions: attention matrices
      **kwargs: arguments to be ignored
    """
    main_content = self.start_sent(idx)
    src_str, trg_str = self.add_sent_in_out(main_content, output, output_proc, src, src_vocab, reference)
    self.add_atts(attentions, main_content, src, src_str, trg_str, idx)
    self.write_html_tree()

  def add_atts(self, attentions, main_content, src, src_str, trg_str, idx, desc="Attentions"):
    src_is_speech = isinstance(src, xnmt.input.ArrayInput)
    if src_is_speech:
      src_feat_file = f"{self.report_path}.src_feat.{idx}.png"
      xnmt.plot.plot_speech_features(src.get_array(), file_name=src_feat_file)
    attention = etree.SubElement(main_content, 'p')
    att_text = etree.SubElement(attention, 'b')
    att_text.text = f"{desc}:"
    etree.SubElement(attention, 'br')
    attention_file = f"{self.report_path}.{util.valid_filename(desc).lower()}.{idx}.png"
    table = etree.SubElement(attention, 'table')
    table_tr = etree.SubElement(table, 'tr')
    table_td1 = etree.SubElement(table_tr, 'td')
    table_td2 = etree.SubElement(table_tr, 'td')
    if src_is_speech:
      att_img = etree.SubElement(table_td1, 'img')
      att_img.attrib['src'] = os.path.basename(src_feat_file)
      att_img.attrib['alt'] = 'speech features'
    att_img = etree.SubElement(table_td2, 'img')
    att_img.attrib['src'] = os.path.basename(attention_file)
    att_img.attrib['alt'] = 'attention matrix'
    xnmt.plot.plot_attention(src_str.split(), trg_str.split(), attentions, file_name=attention_file)


class SegmentingHtmlReporter(HtmlReporter, Serializable):
  """
  A reporter to be used with the segmenting encoder (TODO: untested)
  """
  yaml_tag = "!SegmentingHtmlReporter"

  @serializable_init
  def __init__(self, report_path: str = settings.DEFAULT_REPORT_PREFIX):
    super().__init__(report_path=report_path)

  def create_report(self, segmentation, src, src_vocab, idx, output, output_proc: xnmt.output.OutputProcessor,
                    **kwargs):
    main_content = self.start_sent(idx)
    src_str, trg_str = self.add_sent_in_out(main_content, output, output_proc, src, src_vocab)

    segment_decision = segmentation
    segment_decision = [int(x[0]) for x in segment_decision]
    src_words = [escape(x) for x in src_str.split()]
    # construct the sub element from string
    segmented = self.apply_segmentation(src_words, segment_decision)
    segmented = [(x if not delete else ("<font color='red'><del>" + x + "</del></font>")) for x, delete in segmented]
    if len(segmented) > 0:
      segment_html = "<p>Segmentation: " + ", ".join(segmented) + "</p>"
      main_content.insert(2, etree.fromstring(segment_html))

    self.write_html_tree()

  def apply_segmentation(self, words, segmentation):
    assert(len(words) == len(segmentation))
    segmented = []
    temp = ""
    for decision, word in zip(segmentation, words):
      if decision == 0: #SegmentingAction.READ.value:
        temp += word
      elif decision == 1: #SegmentingAction.SEGMENT.value:
        temp += word
        segmented.append((temp, False))
        temp = ""
      else: # Case: DELETE
        if temp: segmented.append((temp, False))
        segmented.append((word, True))
        temp = ""
    if temp: segmented.append((temp, False))
    return segmented

