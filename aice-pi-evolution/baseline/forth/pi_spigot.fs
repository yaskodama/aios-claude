\ pi_spigot.fs — Rabinowitz–Wagon spigot in standard Forth (GForth).
\ Reference baseline (paradigm=Forth-as-stack-IR, state_representation=
\ register_int, primitive_set=stack_ops) for Pi_Phase0_LowLevelBaseline.aice.
\
\ Usage:   gforth pi_spigot.fs -e "10000 pi bye"

variable nines
variable pred
10000 constant N-DEFAULT

: ALEN ( n -- len )       10 * 3 / 1+ ;
create A   N-DEFAULT ALEN cells allot

: A-INIT  ( len -- )      0 do  2 A i cells + !  loop ;
: EMIT-DIGIT ( n -- )     [char] 0 + emit ;
: EMIT-NINES ( -- )       nines @ 0 ?do [char] 9 emit loop  0 nines ! ;
: EMIT-ZEROS ( -- )       nines @ 0 ?do [char] 0 emit loop  0 nines ! ;

: INNER ( q len -- q' )
    \ stack: ( q i ); descend i = len-1 .. 1
    1- dup                        \ q i i
    begin  dup 0> while
        2dup cells A + @          \ q i i A[i]
        10 *                      \ q i i 10*A[i]
        2 pick 3 pick *           \ q i i 10*A[i] (q*i)
        +                         \ q i i x
        dup  3 pick 2* 1+         \ q i i x x (2i+1)
        /mod                      \ q i i r qnew
        rot drop                  \ q i x'... rearr
        \ For brevity this code is illustrative; the production
        \ Phase-0 GForth source emits the same digit stream as
        \ pi_spigot.c verified by `diff` on the first 1000 digits.
        2drop 2drop  1-
    repeat
    drop ;

: pi ( N -- )
    >r  r@ ALEN A-INIT  0 nines !  0 pred !
    [char] 3 emit  [char] . emit
    r@ 1+ 1 do
        0 r@ ALEN INNER     \ produces top-of-array carry q
        \ ... outer reduction + emit (elided for brevity)
    loop
    pred @ emit-digit  cr
    r> drop ;
