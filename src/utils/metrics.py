#!/usr/bin/env python
import collections
from abc import ABC, abstractmethod

import numpy as np
from scipy.integrate import simps
from scipy.stats import pearsonr, spearmanr, norm, kendalltau
from sklearn.calibration import calibration_curve
import sklearn.metrics
from sklearn.metrics import average_precision_score


def inference_evaluate(y_true: np.ndarray, y_pred: np.ndarray):

    stats = collections.OrderedDict()
    metrics = {
        'R^2': sklearn.metrics.r2_score,
        'MAE': sklearn.metrics.mean_absolute_error
        # 'kendall': lambda x, y: scipy.stats.kendalltau(x, y)[0]
    }

    for key, metric_fn in metrics.items():
        stats[f'{key}'] = metric_fn(y_true, y_pred)

    return stats

def calibration_evaluate(y_true: np.ndarray, y_pred: np.ndarray, y_err: np.ndarray):

    stats = collections.OrderedDict()
    
    metrics = {
        'MMC': MaximumMiscalibration().compute,
        'AMC': AbsoluteMiscalibrationArea().compute
        # 'kendall': lambda x, y: scipy.stats.kendalltau(x, y)[0]
    }

    for key, metric_fn in metrics.items():
        stats[f'{key}'] = metric_fn(y_true, y_pred, y_err)

    scorer = CVPPDiagram()
    qs, Cqs = scorer.compute(y_true, y_pred, y_err, num_bins=30)


    return stats, qs, Cqs

    
class AbstractRegressionMetric(ABC):
    ''' This class implements uncertainty metrics for regression
    tasks

    required methods:
        - compute
    '''

    @abstractmethod
    def compute(self, y_true, y_pred, y_err, **kwargs):
        ''' compute the metric

        Args:
            y_true (np.ndarray): array of true targets , shape (# samples, # targets)
            y_pred (np.ndarray): array of predictive means, shape (# samples, # targets)
            y_err (np.ndarray): array of predictive stds, shape (# samples, # targets)

        Returns:
            res (np.ndarray): the metric value
        '''

# Regression -------------------------------------------------------------------

class RegressionSpearman(AbstractRegressionMetric):
    ''' Spearman's correlation coefficient between the models absolute error
    and the uncertainty - non-linear correlation
    '''

    def __init__(self, name='spearman'):
        self.name = name

    def compute(self, y_true, y_pred, y_err):
        ae = np.abs(y_true - y_pred)
        res, _ = spearmanr(ae.ravel(), y_err.ravel())
        return res


class RegressionPearson(AbstractRegressionMetric):
    ''' Pearson's correlation coefficient between the models absolute error
    and the uncertainty - linear correlation
    '''

    def __init__(self, name='pearson'):
        self.name = name

    def compute(self, y_true, y_pred, y_err):
        ae = np.abs(y_true - y_pred)
        res, _ = pearsonr(ae.ravel(), y_err.ravel())
        return res


class RegressionKendall(AbstractRegressionMetric):
    ''' Kendall's correlation coefficient between the models absolute error
    and the uncertainty - linear correlation
    '''

    def __init__(self, name='kendall'):
        self.name = name

    def compute(self, y_true, y_pred, y_err):
        ae = np.abs(y_true - y_pred)
        res, _ = kendalltau(ae.ravel(), y_err.ravel())
        return res


class CVPPDiagram(AbstractRegressionMetric):
    ''' Metric introduced in arXiv:2010.01118 [cs.LG] based on cross-validatory
    predictive p-values
    '''

    def __init__(self, name='cvpp'):
        self.name = name

    @staticmethod
    def c(y_true, y_pred, y_err, q):
        lhs = np.abs((y_pred - y_true) / y_err)
        rhs = norm.ppf(((1.0 + q) / 2.0), loc=0., scale=1.)
        return np.sum((lhs < rhs).astype(int)) / y_true.shape[0]

    def compute(self, y_true, y_pred, y_err, num_bins=10):
        qs = np.linspace(0, 1, num_bins)
        Cqs = np.empty(qs.shape)
        for ix, q in enumerate(qs):
            Cqs[ix] = self.c(y_true, y_pred, y_err, q)

        return qs, Cqs


class MaximumMiscalibration(AbstractRegressionMetric):
    ''' Miscalibration area metric with CVPP
    WARNING - this metric only diagnoses systematic over- or under-
    confidence, i.e. a model that is overconfident for ~half of the
    quantiles and under-confident for ~half will still have a MiscalibrationArea
    of ~0.
    '''

    def __init__(self, name='mmc'):
        self.name = name

    def compute(self, y_true, y_pred, y_err, num_bins=10):
        scorer = CVPPDiagram()
        qs, Cqs = scorer.compute(y_true, y_pred, y_err, num_bins=num_bins)

        # compute area
        res = np.max(np.abs(Cqs - qs))
        return res


class MiscalibrationArea(AbstractRegressionMetric):
    ''' Miscalibration area metric with CVPP
    WARNING - this metric only diagnoses systematic over- or under-
    confidence, i.e. a model that is overconfident for ~half of the
    quantiles and under-confident for ~half will still have a MiscalibrationArea
    of ~0.
    '''

    def __init__(self, name='ma'):
        self.name = name

    def compute(self, y_true, y_pred, y_err, num_bins=10):
        scorer = CVPPDiagram()
        qs, Cqs = scorer.compute(y_true, y_pred, y_err, num_bins=num_bins)

        # compute area
        res = simps(Cqs - qs, qs)
        return res


class AbsoluteMiscalibrationArea(AbstractRegressionMetric):
    ''' absolute miscalibration area metric with CVPP
    '''

    def __init__(self, name='ama'):
        self.name = name

    def compute(self, y_true, y_pred, y_err, num_bins=10):
        scorer = CVPPDiagram()
        qs, Cqs = scorer.compute(y_true, y_pred, y_err, num_bins=num_bins)

        # compute area
        res = simps(np.abs(Cqs - qs), qs)
        return res


class NLL(AbstractRegressionMetric):
    ''' Negative log-likelihood
    '''

    def __init__(self, name='nll'):
        self.name = name

    def compute(self, y_true, y_pred, y_err, **kwargs):
        res = 1. / (2. * y_true.shape[0]) + y_true.shape[0] * np.log(2 * np.pi) \
              + np.sum(np.log(y_pred)) + np.sum(np.square(y_pred - y_true) / y_err)
        return res


class CalibratedNLL(AbstractRegressionMetric):
    ''' calibrated negative log-likelihood - calibrate the uncertainty
    so that it more closely resembles variances, this assumes the two are
    linearly related. This can be used for UQ methods whose uncertainty estimates
    are not intended to be used as variances (e.g. distances-)

    i.e. sigma^2(x) = a*U(x) + b
    '''

    def __init__(self, name='cnll'):
        self.name = name

    def compute(self, y_true, y_pred, y_err, **kwargs):
        # TODO : implement this
        return None



if __name__ == '__main__':
    pass
