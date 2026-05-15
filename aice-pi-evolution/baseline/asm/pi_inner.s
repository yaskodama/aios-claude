; pi_inner.s — x86-64 SysV inner loop for the Rabinowitz–Wagon spigot.
;
; Reference baseline used by Pi_Phase0_LowLevelBaseline.aice as the
; lowest-tier seed (paradigm=assembler, type_safety=none).
;
; Only the hottest loop is hand-coded:
;
;     for (i = LEN-1; i > 0; i--) {
;         x    = 10*A[i] + q*i;
;         A[i] = x % (2*i+1);
;         q    = x / (2*i+1);
;     }
;
; Called from C as:
;     extern uint64_t spigot_inner(int *A, int LEN);
;
; Returns the final carry `q`.  The outer loop, emit logic, and the
; final A[0] reduction stay in C — assembler buys ~2x on the inner
; mul/div pair because GCC keeps a memory-form imul and idiv.

        .intel_syntax noprefix
        .text
        .globl  spigot_inner
spigot_inner:
        ; rdi = int *A, rsi = LEN
        xor     rax, rax            ; q = 0
        mov     ecx, esi
        dec     ecx                 ; i = LEN-1
.Lloop:
        test    ecx, ecx
        jle     .Ldone

        mov     edx, [rdi + rcx*4]  ; A[i]
        lea     r8d, [rdx + rdx*4]  ; r8 = 5*A[i]
        shl     r8d, 1              ; r8 = 10*A[i]
        mov     r9, rax             ; r9 = q
        imul    r9, rcx             ; r9 = q*i
        add     r9, r8              ; r9 = 10*A[i] + q*i  (= x)

        lea     r10d, [rcx + rcx]   ; r10 = 2*i
        inc     r10d                ; r10 = 2*i + 1

        mov     rax, r9
        xor     rdx, rdx
        div     r10                 ; rax = x/(2i+1), rdx = x%(2i+1)
        mov     [rdi + rcx*4], edx  ; A[i] = remainder

        dec     ecx
        jmp     .Lloop
.Ldone:
        ret
