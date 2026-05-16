// parallel_oo_go.go — π to N decimal digits via Chudnovsky binary
//                     splitting, with goroutines parallelising the
//                     two halves of the recursion.
//
// Build:  go build -o parallel_oo_go parallel_oo_go.go
// Run  :  ./parallel_oo_go            # default N = 10000
//
// Go is not strictly OO, but its method-on-struct discipline plus
// the goroutine + channel concurrency model is the closest analogue
// to "parallel object-oriented" (cf. Erlang processes, Pony actors).
// Each PQT recursion splits into two goroutines down to a depth
// limit, after which it stays serial.
package main

import (
    "fmt"
    "math/big"
    "os"
    "runtime"
    "strconv"
    "time"
)

const (
    A     = int64(13591409)
    B     = int64(545140134)
    C3_24 = int64(10939058860032000) // 640320^3 / 24
)

// PQT is the Chudnovsky binary-splitting triple.
type PQT struct{ P, Q, T *big.Int }

func newPQT() *PQT {
    return &PQT{P: new(big.Int), Q: new(big.Int), T: new(big.Int)}
}

// Combine returns r := L · R (i.e. r.P = L.P*R.P, r.Q = L.Q*R.Q,
//                                r.T = L.T*R.Q + L.P*R.T).
func (r *PQT) Combine(L, R *PQT) *PQT {
    var tmp big.Int
    r.T.Mul(L.T, R.Q)
    tmp.Mul(L.P, R.T)
    r.T.Add(r.T, &tmp)
    r.P.Mul(L.P, R.P)
    r.Q.Mul(L.Q, R.Q)
    return r
}

// leaf fills r with the k-th Chudnovsky leaf.
func leaf(r *PQT, k int64) {
    if k == 0 {
        r.P.SetInt64(1)
        r.Q.SetInt64(1)
        r.T.SetInt64(A)
        return
    }
    r.P.SetInt64(-(6*k - 5) * (2*k - 1) * (6*k - 1))
    r.Q.SetInt64(k * k * k)
    r.Q.Mul(r.Q, big.NewInt(C3_24))
    r.T.SetInt64(A + B*k)
    r.T.Mul(r.T, r.P)
}

// bsplit recursively splits [a, b).  `depth` parallelism: split into
// goroutines until depth == 0.
func bsplit(a, b int64, depth int) *PQT {
    if b-a == 1 {
        r := newPQT()
        leaf(r, a)
        return r
    }
    m := (a + b) / 2
    if depth == 0 {
        L := bsplit(a, m, 0)
        R := bsplit(m, b, 0)
        return newPQT().Combine(L, R)
    }
    // parallel: spawn the right half, run the left here.
    rch := make(chan *PQT, 1)
    go func() { rch <- bsplit(m, b, depth-1) }()
    L := bsplit(a, m, depth-1)
    R := <-rch
    return newPQT().Combine(L, R)
}

// isqrtBig computes ⌊√n⌋ for non-negative big.Int via Newton's method.
func isqrtBig(n *big.Int) *big.Int {
    if n.Sign() < 0 {
        panic("isqrt: negative")
    }
    if n.Sign() == 0 {
        return new(big.Int)
    }
    bits := n.BitLen()
    x := new(big.Int).Lsh(big.NewInt(1), uint(bits/2+1))
    y := new(big.Int)
    div := new(big.Int)
    for {
        div.Quo(n, x)
        y.Add(x, div)
        y.Rsh(y, 1)
        if y.Cmp(x) >= 0 {
            return x
        }
        x.Set(y)
    }
}

func chudnovskyPi(digits int) string {
    nTerms := int64(digits/14 + 2)
    // log2(nTerms): each parallel level halves; cap at #CPUs.
    maxDepth := 0
    for n := nTerms; n > 1; n >>= 1 {
        maxDepth++
    }
    cpus := runtime.NumCPU()
    depth := 0
    for (1 << depth) < cpus && depth < maxDepth {
        depth++
    }
    root := bsplit(0, nTerms, depth)

    // π = 426880·√10005 / S   where S = T/Q
    // ⇒ π = 426880·√10005·Q / T  (scaled by 10^digits for integer output)
    scaleSq := new(big.Int).Exp(big.NewInt(10), big.NewInt(int64(2*digits)), nil)
    sqrtArg := new(big.Int).Mul(big.NewInt(10005), scaleSq)
    sqrtVal := isqrtBig(sqrtArg)
    num := new(big.Int).Mul(big.NewInt(426880), sqrtVal)
    num.Mul(num, root.Q)
    piInt := new(big.Int).Quo(num, root.T)
    s := piInt.String()
    return s[:1] + "." + s[1:]
}

func main() {
    n := 10000
    if len(os.Args) > 1 {
        v, err := strconv.Atoi(os.Args[1])
        if err == nil {
            n = v
        }
    }
    t0 := time.Now()
    result := chudnovskyPi(n)
    elapsed := time.Since(t0)
    fmt.Println(result)
    fmt.Fprintf(os.Stderr, "elapsed_ms=%.3f  cpus=%d\n",
        float64(elapsed.Microseconds())/1000.0, runtime.NumCPU())
}
