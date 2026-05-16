// modern_node.mjs — π to N decimal digits via Chudnovsky binary
//                   splitting, in modern JavaScript (Node.js v20+).
//
// Uses native BigInt only (no external libraries). ES module syntax,
// top-level await, optional chaining — all the modern goodies.
//
// Run:  node modern_node.mjs           # default 10000
//       node modern_node.mjs 1000
//
// Algorithm identical to the C / OCaml / Go versions:  Chudnovsky
// bsplit leaf, combine triple, integer-scaled sqrt for final π.

import { performance } from 'node:perf_hooks';

const A     = 13591409n;
const B     = 545140134n;
const C3_24 = 10939058860032000n;      // 640320^3 / 24

const leaf = (k) => {
    if (k === 0n) return { P: 1n, Q: 1n, T: A };
    const P = -(6n * k - 5n) * (2n * k - 1n) * (6n * k - 1n);
    const Q = k * k * k * C3_24;
    const T = P * (A + B * k);
    return { P, Q, T };
};

const combine = (L, R) => ({
    P: L.P * R.P,
    Q: L.Q * R.Q,
    T: L.T * R.Q + L.P * R.T,
});

const bsplit = (a, b) => {
    if (b - a === 1n) return leaf(a);
    const m = (a + b) / 2n;
    return combine(bsplit(a, m), bsplit(m, b));
};

// Integer square root for BigInt via Newton's method.
const isqrt = (n) => {
    if (n < 0n) throw new Error('isqrt: negative');
    if (n === 0n) return 0n;
    let bits = 0n;
    for (let x = n; x > 0n; x >>= 1n) bits++;
    let x = 1n << ((bits >> 1n) + 1n);
    while (true) {
        const y = (x + n / x) >> 1n;
        if (y >= x) return x;
        x = y;
    }
};

const chudnovskyPi = (digits) => {
    const nTerms  = BigInt(Math.floor(digits / 14) + 2);
    const root    = bsplit(0n, nTerms);
    const scaleSq = 10n ** BigInt(2 * digits);
    const sqrtArg = 10005n * scaleSq;
    const sqrtVal = isqrt(sqrtArg);
    const num     = 426880n * sqrtVal * root.Q;
    const piInt   = num / root.T;          // π · 10^digits
    const s       = piInt.toString();
    return s[0] + '.' + s.slice(1);
};

const n = process.argv.length > 2 ? parseInt(process.argv[2], 10) : 10000;
const t0 = performance.now();
const result = chudnovskyPi(n);
const t1 = performance.now();
console.log(result);
console.error(`elapsed_ms=${(t1 - t0).toFixed(3)}`);
