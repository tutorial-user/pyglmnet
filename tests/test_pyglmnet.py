import numpy as np
import scipy.sparse as sps
from sklearn.cross_validation import KFold, cross_val_score
from sklearn.datasets import make_regression, make_classification
from sklearn.preprocessing import StandardScaler

from nose.tools import assert_true, assert_equal, assert_raises
from numpy.testing import assert_allclose

from pyglmnet import GLM

def test_group_lasso():
    """Group Lasso test."""
    n_samples, n_features = 100, 90

    # assign group ids
    groups = np.zeros(90)
    groups[0:29] = 1
    groups[30:59] = 2
    groups[60:] = 3

    # sample random coefficients
    beta0 = np.random.normal(0.0, 1.0, 1)
    beta = np.random.normal(0.0, 1.0, n_features)
    beta[groups == 2] = 0.

    # create an instance of the GLM class
    glm_group = GLM(distr='poisson', alpha=1.)

    # simulate training data
    Xr = np.random.normal(0.0, 1.0, [n_samples, n_features])
    yr = glm_group.simulate(beta0, beta, Xr)

    # simulate testing data
    Xt = np.random.normal(0.0, 1.0, [n_samples, n_features])
    yt = glm_group.simulate(beta0, beta, Xt)

    # scale and fit
    scaler = StandardScaler().fit(Xr)
    glm_group.fit(scaler.transform(Xr), yr)

def test_glmnet():
    """Test glmnet."""
    scaler = StandardScaler()
    n_samples, n_features = 1000, 100
    density = 0.1
    n_lambda = 10

    # coefficients
    beta0 = 1. / (np.float(n_features) + 1.) * \
        np.random.normal(0.0, 1.0)
    beta = 1. / (np.float(n_features) + 1.) * \
        np.random.normal(0.0, 1.0, [n_features, 1])

    distrs = ['poisson', 'poissonexp', 'normal', 'binomial']
    solvers = ['batch-gradient', 'cdfast']
    learning_rate = 2e-1

    for solver in solvers:
        for distr in distrs:

            glm = GLM(distr, learning_rate=learning_rate,
                      solver=solver)

            assert_true(repr(glm))

            np.random.seed(glm.random_state)
            X_train = np.random.normal(0.0, 1.0, [n_samples, n_features])
            y_train = glm.simulate(beta0, beta, X_train)

            X_train = scaler.fit_transform(X_train)
            glm.fit(X_train, y_train)

            beta_ = glm.fit_[-1]['beta'][:]
            assert_allclose(beta[:], beta_, atol=0.5)  # check fit

            y_pred = glm.predict(scaler.transform(X_train))
            assert_equal(y_pred.shape, (n_lambda, X_train.shape[0]))

    # checks for slicing.
    glm = glm[:3]
    glm_copy = glm.copy()
    assert_true(glm_copy is not glm)
    assert_equal(len(glm.reg_lambda), 3)
    y_pred = glm[:2].predict(scaler.transform(X_train))
    assert_equal(y_pred.shape, (2, X_train.shape[0]))
    y_pred = glm[2].predict(scaler.transform(X_train))
    assert_equal(y_pred.shape, (X_train.shape[0], ))
    assert_raises(IndexError, glm.__getitem__, [2])
    glm.score(y_train, y_pred)

    # don't allow slicing if model has not been fit yet.
    glm_poisson = GLM(distr='poisson')
    assert_raises(ValueError, glm_poisson.__getitem__, 2)

    # test fit_predict
    glm_poisson.fit_predict(X_train, y_train)
    assert_raises(ValueError, glm_poisson.fit_predict, X_train[None, ...], y_train)


def simple_cv_scorer(obj, X, y):
    """Simple scorer takes average pseudo-R2 from regularization path"""
    yhats = obj.predict(X)
    ynull = np.zeros(y.shape) * y.mean()
    return np.mean([obj.score(y, yhat, ynull, method='pseudo_R2')
                   for yhat in yhats])


def test_cv():
    """Simple CV check"""
    # XXX: don't use scikit-learn for tests.
    X, y = make_regression()

    glm_normal = GLM(distr='normal', alpha=0.01,
                     reg_lambda=[0.0, 0.1, 0.2])
    glm_normal.fit(X, y)

    cv = KFold(X.shape[0], 5)
    # check that it returns 5 scores

    assert_equal(len(cross_val_score(glm_normal, X, y, cv=cv,
                 scoring=simple_cv_scorer)), 5)

def test_multinomial():
    """Test all multinomial functionality"""
    glm_mn = GLM(distr='multinomial', reg_lambda=np.array([0.0, 0.1, 0.2]),
                 learning_rate = 2e-1, tol=1e-10)
    X = np.array([[-1, -2, -3], [4, 5, 6]])
    y = np.array([1, 0])

    # test gradient
    beta = np.zeros([4, 2])
    grad_beta0, grad_beta = glm_mn._grad_L2loss(beta[0], beta[1:], 0, X, y)
    assert_true(grad_beta0[0] != grad_beta0[1])
    glm_mn.fit(X, y)
    y_pred = glm_mn.predict(X)
    assert_equal(y_pred.shape, (3, X.shape[0], 2))  # n_lambdas x n_samples x n_classes

    # pick one as yhat
    yhat = y_pred[0]
    # uniform prediction
    ynull = np.ones(yhat.shape) / yhat.shape[1]
    # pseudo_R2 should be greater than 0
    assert_true(glm_mn.score(y, yhat, ynull, method='pseudo_R2') > 0.)
    glm_mn.score(y, yhat)
    assert_equal(len(glm_mn.simulate(glm_mn.fit_[0]['beta0'],
                                  glm_mn.fit_[0]['beta'],
                                  X)),
                 X.shape[0])
    # these should raise an exception
    assert_raises(ValueError, glm_mn.score, y, y, y, 'pseudo_R2')
    assert_raises(ValueError, glm_mn.score, y, y, None, 'deviance')

def test_cdfast():
    """Test all functionality related to fast coordinate descent"""
    scaler = StandardScaler()
    n_samples = 1000
    n_features = 100
    n_classes = 5
    density = 0.1

    distrs = ['poisson', 'poissonexp', 'normal', 'binomial', 'multinomial']
    for distr in distrs:
        glm = GLM(distr, solver='cdfast')

        np.random.seed(glm.random_state)
        if distr != 'multinomial':
            # coefficients
            beta0 = np.random.rand()
            beta = sps.rand(n_features, 1, density=density).toarray()
            # data
            X = np.random.normal(0.0, 1.0, [n_samples, n_features])
            X = scaler.fit_transform(X)
            y = glm.simulate(beta0, beta, X)

        elif distr == 'multinomial':
            # coefficients
            beta0 = 1 / (n_features + 1) * \
                np.random.normal(0.0, 1.0, n_classes)
            beta = 1 / (n_features + 1) * \
                np.random.normal(0.0, 1.0, [n_features, n_classes])
            # data
            X, y = make_classification(n_samples=n_samples,
                                       n_features=n_features,
                                       n_redundant=0,
                                       n_informative=n_features,
                           random_state=1, n_classes=n_classes)
            y_bk = y.ravel()
            y = np.zeros([X.shape[0], y.max() + 1])
            y[np.arange(X.shape[0]), y_bk] = 1

        # compute grad and hess
        beta_ = np.zeros([n_features+1, beta.shape[1]])
        beta_[0] = beta0
        beta_[1:] = beta
        z = beta_[0] + np.dot(X, beta_[1:])
        k = 1
        xk = np.expand_dims(X[:, k - 1], axis=1)
        gk, hk = glm._gradhess_logloss_1d(xk, y, z)

        # test grad and hess
        if distr != 'multinomial':
            assert_equal(np.size(gk), 1)
            assert_equal(np.size(hk), 1)
            assert_true(isinstance(gk, float))
            assert_true(isinstance(hk, float))
        else:
            assert_equal(gk.shape[0], n_classes)
            assert_equal(hk.shape[0], n_classes)
            assert_true(isinstance(gk, np.ndarray))
            assert_true(isinstance(hk, np.ndarray))
            assert_equal(gk.ndim, 1)
            assert_equal(hk.ndim, 1)

        # test cdfast
        ActiveSet = np.ones(n_features + 1)
        rl = glm.reg_lambda[0]
        beta_ret, z_ret = glm._cdfast(X, y, z, ActiveSet, beta_, rl)
        assert_equal(beta_ret.shape, beta_.shape)
        assert_equal(z_ret.shape, z.shape)
