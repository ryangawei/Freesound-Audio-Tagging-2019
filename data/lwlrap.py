import numpy as np
import tensorflow as tf
import sklearn.metrics as metrics


def _one_sample_positive_class_precisions(scores, truth):
    """Calculate precisions for each true class for a single sample.

    Args:
      scores: np.array of (num_classes,) giving the individual classifier scores.
      truth: np.array of (num_classes,) bools indicating which classes are true.
    Returns:
      pos_class_indices: np.array of indices of the true classes for this sample.
      pos_class_precisions: np.array of precisions corresponding to each of those
        classes.
    """
    num_classes = scores.shape[0]
    pos_class_indices = np.flatnonzero(truth > 0)
    # Only calculate precisions if there are some true classes.
    if not len(pos_class_indices):
        return pos_class_indices, np.zeros(0)
    # Retrieval list of classes for this sample.
    retrieved_classes = np.argsort(scores)[::-1]
    # class_rankings[top_scoring_class_index] == 0 etc.
    class_rankings = np.zeros(num_classes, dtype=np.int)
    class_rankings[retrieved_classes] = range(num_classes)
    # Which of these is a true label?
    retrieved_class_true = np.zeros(num_classes, dtype=np.bool)
    retrieved_class_true[class_rankings[pos_class_indices]] = True
    # Num hits for every truncated retrieval list.
    retrieved_cumulative_hits = np.cumsum(retrieved_class_true)
    # Precision of retrieval list truncated at each hit, in order of pos_labels.
    precision_at_hits = (
            retrieved_cumulative_hits[class_rankings[pos_class_indices]] /
            (1 + class_rankings[pos_class_indices].astype(np.float)))
    return pos_class_indices, precision_at_hits


def calculate_per_class_lwlrap(truth, scores):
    """Calculate label-weighted label-ranking average precision.

    Arguments:
      truth: np.array of (num_samples, num_classes) giving boolean ground-truth
        of presence of that class in that sample.
      scores: np.array of (num_samples, num_classes) giving the classifier-under-
        test's real-valued score for each class for each sample.

    Returns:
      per_class_lwlrap: np.array of (num_classes,) giving the lwlrap for each
        class.
      weight_per_class: np.array of (num_classes,) giving the prior of each
        class within the truth labels.  Then the overall unbalanced lwlrap is
        simply np.sum(per_class_lwlrap * weight_per_class)
    """
    assert truth.shape == scores.shape
    num_samples, num_classes = scores.shape
    # Space to store a distinct precision value for each class on each sample.
    # Only the classes that are true for each sample will be filled in.
    precisions_for_samples_by_classes = np.zeros((num_samples, num_classes))
    for sample_num in range(num_samples):
        pos_class_indices, precision_at_hits = (
            _one_sample_positive_class_precisions(scores[sample_num, :],
                                                  truth[sample_num, :]))
        precisions_for_samples_by_classes[sample_num, pos_class_indices] = (
            precision_at_hits)
    labels_per_class = np.sum(truth > 0, axis=0)
    weight_per_class = labels_per_class / float(np.sum(labels_per_class))
    # Form average of each column, i.e. all the precisions assigned to labels in
    #     # a particular class.
    per_class_lwlrap = (np.sum(precisions_for_samples_by_classes, axis=0) /
                        np.maximum(1, labels_per_class))
    # overall_lwlrap = simple average of all the actual per-class, per-sample precisions
    #                = np.sum(precisions_for_samples_by_classes) / np.sum(precisions_for_samples_by_classes > 0)
    #           also = weighted mean of per-class lwlraps, weighted by class label prior across samples
    #                = np.sum(per_class_lwlrap * weight_per_class)
    return per_class_lwlrap, weight_per_class


def tf_one_sample_positive_class_precisions(y_true, y_pred):
        num_samples, num_classes = y_pred.shape
        # find true labels
        pos_class_indices = tf.where(y_true > 0)
        # put rank on each element
        retrieved_classes = tf.nn.top_k(y_pred, k=num_classes).indices
        sample_range = tf.zeros(shape=tf.shape(tf.transpose(y_pred)), dtype=tf.int32)
        sample_range = tf.add(sample_range, tf.range(tf.shape(y_pred)[0], delta=1))
        sample_range = tf.transpose(sample_range)
        sample_range = tf.reshape(sample_range, (-1, num_classes * tf.shape(y_pred)[0]))
        retrieved_classes = tf.reshape(retrieved_classes, (-1, num_classes * tf.shape(y_pred)[0]))
        retrieved_class_map = tf.concat((sample_range, retrieved_classes), axis=0)
        retrieved_class_map = tf.transpose(retrieved_class_map)
        retrieved_class_map = tf.reshape(retrieved_class_map, (tf.shape(y_pred)[0], num_classes, 2))
        class_range = tf.zeros(shape=tf.shape(y_pred), dtype=tf.int32)
        class_range = tf.add(class_range, tf.range(num_classes, delta=1))
        class_rankings = tf.scatter_nd(retrieved_class_map,
                                       class_range,
                                       tf.shape(y_pred))
        # pick_up ranks
        num_correct_until_correct = tf.gather_nd(class_rankings, pos_class_indices)
        # add one for division for "presicion_at_hits"
        num_correct_until_correct_one = tf.add(num_correct_until_correct, 1)
        num_correct_until_correct_one = tf.cast(num_correct_until_correct_one, tf.float32)
        # generate tensor [num_sample, predict_rank],
        # top-N predicted elements have flag, N is the number of positive for each sample.
        sample_label = pos_class_indices[:, 0]
        sample_label = tf.reshape(sample_label, (-1, 1))
        sample_label = tf.cast(sample_label, tf.int32)

        num_correct_until_correct = tf.reshape(num_correct_until_correct, (-1, 1))
        retrieved_class_true_position = tf.concat((sample_label,
                                                   num_correct_until_correct), axis=1)
        retrieved_pos = tf.ones(shape=tf.shape(retrieved_class_true_position)[0], dtype=tf.int32)
        retrieved_class_true = tf.scatter_nd(retrieved_class_true_position,
                                             retrieved_pos,
                                             tf.shape(y_pred))
        # cumulate predict_rank
        retrieved_cumulative_hits = tf.cumsum(retrieved_class_true, axis=1)

        # find positive position
        pos_ret_indices = tf.where(retrieved_class_true > 0)

        # find cumulative hits
        correct_rank = tf.gather_nd(retrieved_cumulative_hits, pos_ret_indices)
        correct_rank = tf.cast(correct_rank, tf.float32)

        # compute presicion
        precision_at_hits = tf.truediv(correct_rank, num_correct_until_correct_one)

        return pos_class_indices, precision_at_hits


def tf_lwlrap(y_true, y_pred):
    num_samples, num_classes = y_pred.shape
    pos_class_indices, precision_at_hits = (tf_one_sample_positive_class_precisions(y_true, y_pred))
    pos_flgs = tf.cast(y_true > 0, tf.int32)
    labels_per_class = tf.reduce_sum(pos_flgs, axis=0)
    weight_per_class = tf.truediv(tf.cast(labels_per_class, tf.float32),
                                  tf.cast(tf.reduce_sum(labels_per_class), tf.float32))
    sum_precisions_by_classes = tf.zeros(shape=(num_classes), dtype=tf.float32)
    class_label = pos_class_indices[:, 1]
    sum_precisions_by_classes = tf.unsorted_segment_sum(precision_at_hits,
                                                        class_label,
                                                        num_classes)
    labels_per_class = tf.cast(labels_per_class, tf.float32)
    labels_per_class = tf.add(labels_per_class, 1e-7)
    per_class_lwlrap = tf.truediv(sum_precisions_by_classes,
                                  tf.cast(labels_per_class, tf.float32))
    out = tf.cast(tf.tensordot(per_class_lwlrap, weight_per_class, axes=1), dtype=tf.float32)
    return out


def calculate_overall_lwlrap_sklearn(truth, scores):
    """Calculate the overall lwlrap using sklearn.metrics.lrap."""
    # sklearn doesn't correctly apply weighting to samples with no labels, so just skip them.
    sample_weight = np.sum(truth > 0, axis=1)
    nonzero_weight_sample_indices = np.flatnonzero(sample_weight > 0)
    overall_lwlrap = metrics.label_ranking_average_precision_score(
        truth[nonzero_weight_sample_indices, :] > 0,
        scores[nonzero_weight_sample_indices, :],
        sample_weight=sample_weight[nonzero_weight_sample_indices])
    return overall_lwlrap

