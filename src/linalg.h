#pragma once

// Linear algebra for EMTSim:
//   Matrix / LUFactor        dense matrix and LU with partial pivoting (small systems, tests)
//   SparseMatrix / SparseLDL sparse matrix and sparse LDL^T factorisation, used by the network
//                            solver: the conductance matrix is sparse, symmetric and positive
//                            definite, so it needs no pivoting.

#include <cstddef>
#include <iosfwd>
#include <string>
#include <vector>

using Vector = std::vector<double>;

class Matrix {
public:
    Matrix(std::size_t rows = 0, std::size_t cols = 0) : rows_(rows), cols_(cols), a_(rows * cols, 0.0) {}

    double& operator()(std::size_t i, std::size_t j) { return a_[i * cols_ + j]; }
    double operator()(std::size_t i, std::size_t j) const { return a_[i * cols_ + j]; }

    std::size_t rows() const { return rows_; }
    std::size_t cols() const { return cols_; }

    // Copy of the sub-matrix starting at (r0, c0) with nr rows and nc columns
    Matrix block(std::size_t r0, std::size_t c0, std::size_t nr, std::size_t nc) const;

    // y = A * x
    Vector operator*(const Vector& x) const;

    void print(std::ostream& os, const std::string& name) const;

private:
    std::size_t rows_, cols_;
    std::vector<double> a_;
};

// Small dense helpers (used by coupled elements: 3x3 blocks and the like)
Matrix operator*(const Matrix& A, const Matrix& B);
Matrix operator+(const Matrix& A, const Matrix& B);
Matrix operator*(double s, const Matrix& A);
Matrix transpose(const Matrix& A);
Matrix inverse(const Matrix& A);   // throws std::runtime_error if singular

// LU factorisation with partial pivoting: P A = L U.
// L (unit diagonal) and U are packed into one matrix, the row swaps in piv_.
class LUFactor {
public:
    void factor(const Matrix& A);       // throws std::runtime_error if A is singular
    Vector solve(const Vector& b) const;

private:
    Matrix lu_;
    std::vector<std::size_t> piv_;
};

// Sparse matrix in compressed sparse column (CSC) form.
// Build it with add() (entries at the same position are summed), then call finalize().
class SparseMatrix {
public:
    SparseMatrix(std::size_t rows = 0, std::size_t cols = 0) : rows_(rows), cols_(cols), colptr_(cols + 1, 0) {}

    void add(std::size_t i, std::size_t j, double v);   // accumulate A(i, j) += v
    void finalize();                                     // sort, merge duplicates, build CSC

    std::size_t rows() const { return rows_; }
    std::size_t cols() const { return cols_; }
    std::size_t nnz() const { return val_.size(); }

    // Copy of the sub-matrix starting at (r0, c0) with nr rows and nc columns
    SparseMatrix block(std::size_t r0, std::size_t c0, std::size_t nr, std::size_t nc) const;
    Vector operator*(const Vector& x) const;             // y = A * x
    Matrix toDense() const;

    // CSC arrays: column j holds rows rowind[colptr[j] .. colptr[j+1]) with values val[...]
    const std::vector<std::size_t>& colptr() const { return colptr_; }
    const std::vector<std::size_t>& rowind() const { return rowind_; }
    const std::vector<double>& val() const { return val_; }

private:
    struct Triplet { std::size_t i, j; double v; };
    std::size_t rows_, cols_;
    std::vector<Triplet> pending_;
    std::vector<std::size_t> colptr_, rowind_;
    std::vector<double> val_;
};

// Fill-reducing ordering: minimum degree on the graph of a symmetric matrix.
std::vector<std::size_t> minimumDegreeOrder(const SparseMatrix& A);

// Sparse LDL^T factorisation of a symmetric positive definite matrix: P A P^T = L D L^T,
// with P a minimum-degree ordering, L unit lower triangular and D diagonal.
// Algorithm: T. A. Davis, "Algorithm 849: A concise sparse Cholesky factorization package",
// ACM TOMS 31(4), 2005 (the LDL package): elimination tree + up-looking numeric factorisation.
class SparseLDL {
public:
    void factor(const SparseMatrix& A);   // A: full symmetric pattern. Throws if (numerically) singular
    Vector solve(const Vector& b) const;
    std::size_t nnzL() const { return Li_.size(); }   // non-zeros below the diagonal of L

private:
    std::size_t n_ = 0;
    std::vector<std::size_t> P_, Pinv_;   // ordering: row k of P A P^T is row P_[k] of A
    std::vector<std::size_t> Lp_, Li_;    // L (strictly lower part) in CSC
    std::vector<double> Lx_, D_;
};
