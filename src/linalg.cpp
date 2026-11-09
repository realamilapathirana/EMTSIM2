#include "linalg.h"

#include <algorithm>
#include <cmath>
#include <iomanip>
#include <limits>
#include <ostream>
#include <set>
#include <stdexcept>
#include <utility>

Matrix Matrix::block(std::size_t r0, std::size_t c0, std::size_t nr, std::size_t nc) const {
    Matrix B(nr, nc);
    for (std::size_t i = 0; i < nr; ++i)
        for (std::size_t j = 0; j < nc; ++j)
            B(i, j) = (*this)(r0 + i, c0 + j);
    return B;
}

Vector Matrix::operator*(const Vector& x) const {
    if (x.size() != cols_) throw std::invalid_argument("Matrix * Vector: size mismatch");
    Vector y(rows_, 0.0);
    for (std::size_t i = 0; i < rows_; ++i)
        for (std::size_t j = 0; j < cols_; ++j)
            y[i] += (*this)(i, j) * x[j];
    return y;
}

void Matrix::print(std::ostream& os, const std::string& name) const {
    os << name << " (" << rows_ << "x" << cols_ << ")\n";
    for (std::size_t i = 0; i < rows_; ++i) {
        os << "  ";
        for (std::size_t j = 0; j < cols_; ++j)
            os << std::setw(12) << std::setprecision(5) << (*this)(i, j);
        os << "\n";
    }
}

Matrix operator*(const Matrix& A, const Matrix& B) {
    if (A.cols() != B.rows()) throw std::invalid_argument("Matrix * Matrix: size mismatch");
    Matrix C(A.rows(), B.cols());
    for (std::size_t i = 0; i < A.rows(); ++i)
        for (std::size_t k = 0; k < A.cols(); ++k)
            for (std::size_t j = 0; j < B.cols(); ++j) C(i, j) += A(i, k) * B(k, j);
    return C;
}

Matrix operator+(const Matrix& A, const Matrix& B) {
    if (A.rows() != B.rows() || A.cols() != B.cols()) throw std::invalid_argument("Matrix + Matrix: size mismatch");
    Matrix C(A.rows(), A.cols());
    for (std::size_t i = 0; i < A.rows(); ++i)
        for (std::size_t j = 0; j < A.cols(); ++j) C(i, j) = A(i, j) + B(i, j);
    return C;
}

Matrix operator*(double s, const Matrix& A) {
    Matrix C(A.rows(), A.cols());
    for (std::size_t i = 0; i < A.rows(); ++i)
        for (std::size_t j = 0; j < A.cols(); ++j) C(i, j) = s * A(i, j);
    return C;
}

Matrix transpose(const Matrix& A) {
    Matrix T(A.cols(), A.rows());
    for (std::size_t i = 0; i < A.rows(); ++i)
        for (std::size_t j = 0; j < A.cols(); ++j) T(j, i) = A(i, j);
    return T;
}

Matrix inverse(const Matrix& A) {
    LUFactor lu;
    lu.factor(A);
    const std::size_t n = A.rows();
    Matrix X(n, n);
    for (std::size_t j = 0; j < n; ++j) {
        Vector e(n, 0.0);
        e[j] = 1.0;
        const Vector x = lu.solve(e);
        for (std::size_t i = 0; i < n; ++i) X(i, j) = x[i];
    }
    return X;
}

void LUFactor::factor(const Matrix& A) {
    if (A.rows() != A.cols()) throw std::invalid_argument("LU: matrix must be square");
    const std::size_t n = A.rows();
    lu_ = A;
    piv_.assign(n, 0);

    for (std::size_t k = 0; k < n; ++k) {
        // Partial pivoting: pick the largest entry in column k
        std::size_t p = k;
        for (std::size_t i = k + 1; i < n; ++i)
            if (std::fabs(lu_(i, k)) > std::fabs(lu_(p, k))) p = i;
        if (std::fabs(lu_(p, k)) < 1e-300)
            throw std::runtime_error("LU: conductance matrix is singular (is there a floating node?)");
        piv_[k] = p;
        if (p != k)
            for (std::size_t j = 0; j < n; ++j) std::swap(lu_(k, j), lu_(p, j));

        for (std::size_t i = k + 1; i < n; ++i) {
            lu_(i, k) /= lu_(k, k);
            for (std::size_t j = k + 1; j < n; ++j)
                lu_(i, j) -= lu_(i, k) * lu_(k, j);
        }
    }
}

Vector LUFactor::solve(const Vector& b) const {
    const std::size_t n = lu_.rows();
    if (b.size() != n) throw std::invalid_argument("LU solve: size mismatch");
    Vector x = b;
    for (std::size_t k = 0; k < n; ++k)              // apply row swaps: P b
        if (piv_[k] != k) std::swap(x[k], x[piv_[k]]);
    for (std::size_t i = 0; i < n; ++i)              // forward substitution: L y = P b
        for (std::size_t j = 0; j < i; ++j) x[i] -= lu_(i, j) * x[j];
    for (std::size_t i = n; i-- > 0;) {              // back substitution: U x = y
        for (std::size_t j = i + 1; j < n; ++j) x[i] -= lu_(i, j) * x[j];
        x[i] /= lu_(i, i);
    }
    return x;
}

// ---------------------------------------------------------------- SparseMatrix

void SparseMatrix::add(std::size_t i, std::size_t j, double v) {
    if (i >= rows_ || j >= cols_) throw std::out_of_range("SparseMatrix::add: index out of range");
    pending_.push_back({i, j, v});
}

void SparseMatrix::finalize() {
    // Merge already finalised entries with the pending ones, then sort by (column, row)
    for (std::size_t j = 0; j < cols_; ++j)
        for (std::size_t p = colptr_[j]; p < colptr_[j + 1]; ++p) pending_.push_back({rowind_[p], j, val_[p]});
    std::sort(pending_.begin(), pending_.end(),
              [](const Triplet& a, const Triplet& b) { return a.j != b.j ? a.j < b.j : a.i < b.i; });
    colptr_.assign(cols_ + 1, 0);
    rowind_.clear();
    val_.clear();
    for (std::size_t k = 0; k < pending_.size();) {
        const std::size_t i = pending_[k].i, j = pending_[k].j;
        double v = 0.0;
        while (k < pending_.size() && pending_[k].i == i && pending_[k].j == j) v += pending_[k++].v;
        rowind_.push_back(i);
        val_.push_back(v);
        ++colptr_[j + 1];
    }
    for (std::size_t j = 0; j < cols_; ++j) colptr_[j + 1] += colptr_[j];
    pending_.clear();
}

SparseMatrix SparseMatrix::block(std::size_t r0, std::size_t c0, std::size_t nr, std::size_t nc) const {
    SparseMatrix B(nr, nc);
    for (std::size_t j = 0; j < nc; ++j) {
        for (std::size_t p = colptr_[c0 + j]; p < colptr_[c0 + j + 1]; ++p) {
            const std::size_t i = rowind_[p];
            if (i >= r0 && i < r0 + nr) {
                B.rowind_.push_back(i - r0);
                B.val_.push_back(val_[p]);
            }
        }
        B.colptr_[j + 1] = B.rowind_.size();
    }
    return B;
}

Vector SparseMatrix::operator*(const Vector& x) const {
    if (x.size() != cols_) throw std::invalid_argument("SparseMatrix * Vector: size mismatch");
    Vector y(rows_, 0.0);
    for (std::size_t j = 0; j < cols_; ++j)
        for (std::size_t p = colptr_[j]; p < colptr_[j + 1]; ++p) y[rowind_[p]] += val_[p] * x[j];
    return y;
}

Matrix SparseMatrix::toDense() const {
    Matrix M(rows_, cols_);
    for (std::size_t j = 0; j < cols_; ++j)
        for (std::size_t p = colptr_[j]; p < colptr_[j + 1]; ++p) M(rowind_[p], j) = val_[p];
    return M;
}

// ---------------------------------------------------------------- ordering

std::vector<std::size_t> minimumDegreeOrder(const SparseMatrix& A) {
    // Eliminate, one at a time, the node with the fewest neighbours in the elimination graph;
    // eliminating a node connects all its neighbours to each other (the fill-in).
    const std::size_t n = A.cols();
    const auto& Ap = A.colptr();
    const auto& Ai = A.rowind();
    std::vector<std::set<std::size_t>> g(n);
    for (std::size_t j = 0; j < n; ++j)
        for (std::size_t p = Ap[j]; p < Ap[j + 1]; ++p)
            if (Ai[p] != j) { g[Ai[p]].insert(j); g[j].insert(Ai[p]); }

    std::vector<char> done(n, 0);
    std::vector<std::size_t> order;
    order.reserve(n);
    for (std::size_t step = 0; step < n; ++step) {
        std::size_t v = 0, best = std::numeric_limits<std::size_t>::max();
        for (std::size_t k = 0; k < n; ++k)
            if (!done[k] && g[k].size() < best) { best = g[k].size(); v = k; }
        order.push_back(v);
        done[v] = 1;
        const std::vector<std::size_t> nb(g[v].begin(), g[v].end());
        for (std::size_t a : nb) g[a].erase(v);
        for (std::size_t x = 0; x < nb.size(); ++x)
            for (std::size_t y = x + 1; y < nb.size(); ++y) { g[nb[x]].insert(nb[y]); g[nb[y]].insert(nb[x]); }
        g[v].clear();
    }
    return order;
}

// ---------------------------------------------------------------- SparseLDL

void SparseLDL::factor(const SparseMatrix& A) {
    if (A.rows() != A.cols()) throw std::invalid_argument("SparseLDL: matrix must be square");
    n_ = A.cols();
    const auto& Ap = A.colptr();
    const auto& Ai = A.rowind();
    const auto& Ax = A.val();
    const std::size_t NONE = std::numeric_limits<std::size_t>::max();

    P_ = minimumDegreeOrder(A);
    Pinv_.assign(n_, 0);
    for (std::size_t k = 0; k < n_; ++k) Pinv_[P_[k]] = k;

    // Symbolic: elimination tree (parent) and the number of non-zeros in each column of L.
    // Only the upper triangle (row <= column) of the permuted matrix is used.
    std::vector<std::size_t> parent(n_), flag(n_), lnz(n_);
    for (std::size_t k = 0; k < n_; ++k) {
        parent[k] = NONE;
        flag[k] = k;
        lnz[k] = 0;
        const std::size_t kk = P_[k];
        for (std::size_t p = Ap[kk]; p < Ap[kk + 1]; ++p) {
            std::size_t i = Pinv_[Ai[p]];
            if (i >= k) continue;
            for (; flag[i] != k; i = parent[i]) {   // walk up the tree from i to the root of row k
                if (parent[i] == NONE) parent[i] = k;
                ++lnz[i];
                flag[i] = k;
            }
        }
    }
    Lp_.assign(n_ + 1, 0);
    for (std::size_t k = 0; k < n_; ++k) Lp_[k + 1] = Lp_[k] + lnz[k];
    Li_.assign(Lp_[n_], 0);
    Lx_.assign(Lp_[n_], 0.0);
    D_.assign(n_, 0.0);

    // Numeric: compute row k of L and D(k) from rows 0..k-1 (up-looking)
    Vector Y(n_, 0.0);
    std::vector<std::size_t> pattern(n_);
    for (std::size_t k = 0; k < n_; ++k) {
        Y[k] = 0.0;
        std::size_t top = n_;
        flag[k] = k;
        lnz[k] = 0;
        double akk = 0.0;
        const std::size_t kk = P_[k];
        for (std::size_t p = Ap[kk]; p < Ap[kk + 1]; ++p) {
            std::size_t i = Pinv_[Ai[p]];
            if (i > k) continue;
            Y[i] += Ax[p];
            if (i == k) akk += Ax[p];
            std::size_t len = 0;
            for (; flag[i] != k; i = parent[i]) {   // non-zero pattern of row k, in topological order
                pattern[len++] = i;
                flag[i] = k;
            }
            while (len > 0) pattern[--top] = pattern[--len];
        }
        D_[k] = Y[k];
        Y[k] = 0.0;
        for (; top < n_; ++top) {
            const std::size_t i = pattern[top];
            const double yi = Y[i];
            Y[i] = 0.0;
            const std::size_t p2 = Lp_[i] + lnz[i];
            for (std::size_t p = Lp_[i]; p < p2; ++p) Y[Li_[p]] -= Lx_[p] * yi;
            const double lki = yi / D_[i];
            D_[k] -= lki * yi;
            Li_[p2] = k;
            Lx_[p2] = lki;
            ++lnz[i];
        }
        if (!(std::fabs(D_[k]) > 1e-13 * std::fabs(akk)) || D_[k] == 0.0)
            throw std::runtime_error("Sparse LDL: conductance matrix is singular (is there a floating node?)");
    }
}

Vector SparseLDL::solve(const Vector& b) const {
    if (b.size() != n_) throw std::invalid_argument("SparseLDL solve: size mismatch");
    Vector x(n_);
    for (std::size_t k = 0; k < n_; ++k) x[k] = b[P_[k]];         // x = P b
    for (std::size_t j = 0; j < n_; ++j)                           // L y = P b
        for (std::size_t p = Lp_[j]; p < Lp_[j + 1]; ++p) x[Li_[p]] -= Lx_[p] * x[j];
    for (std::size_t j = 0; j < n_; ++j) x[j] /= D_[j];            // D z = y
    for (std::size_t j = n_; j-- > 0;)                             // L^T w = z
        for (std::size_t p = Lp_[j]; p < Lp_[j + 1]; ++p) x[j] -= Lx_[p] * x[Li_[p]];
    Vector out(n_);
    for (std::size_t k = 0; k < n_; ++k) out[P_[k]] = x[k];       // x = P^T w
    return out;
}
