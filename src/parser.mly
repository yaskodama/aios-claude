%{
open Ast
open Location
let mk_expr (d : Ast.expr_desc) : Ast.expr = { loc  = Location.dummy; desc  = d }
let mk_stmt (d : Ast.stmt_desc) : Ast.stmt = { sloc = Location.dummy; sdesc = d }
exception Syntax_error of Location.t * string
let loc_of_rhs i =
  let p = Parsing.rhs_start_pos i in
  { line = p.Lexing.pos_lnum; col  = p.Lexing.pos_cnum - p.Lexing.pos_bol + 1 }
let mk_expr1 i d : Ast.expr = { loc = loc_of_rhs i; desc = d }
let mk_stmt1 i d : Ast.stmt = { sloc = loc_of_rhs i; sdesc = d }
%}
%token <string> ID
%token <float> FLOATLIT
%token <int> INTLIT
%token <string> STRINGLIT
%token METHOD FLOAT CALL SEND UNSAFESEND REMOTE
%token NOW FUTURE AWAIT
%token IF THEN ELSE WHILE DO
%token ASSIGN PLUS MINUS TIMES DIV LPAREN RPAREN LBRACE RBRACE LBRACK RBRACK COLON SEMICOLON COMMA
%token GE LE GT LT SELF SENDER CLASS
%token SELECT CASE TIMEOUT
%token ARROW /* -> */
%token EOF NEW
%token VAR EQ NEQ DOT BECOME FUNCTION RETURN
%token WHERE AND_KW OR_KW NOT_KW   /* O-2.a: refinement-type predicates */
/* Precedence and associativity, lowest to highest.
   Aim: keep the grammar at exactly one shift/reduce conflict —
   the canonical "dangling else" (IF ... stmt vs IF ... stmt ELSE stmt).
   Everything else is disambiguated here. */
%nonassoc IFX             /* below ELSE so `if (e) stmt` reduces only
                             when no ELSE follows */
%nonassoc ELSE
%left EQ NEQ              /* equality:   a == b == c parses ((a==b)==c) */
%left LT GT LE GE         /* relational: a < b < c   parses ((a<b)<c) */
%left PLUS MINUS          /* additive */
%left TIMES DIV           /* multiplicative */
%left DOT LBRACK          /* postfix access — tightest */
%nonassoc UAWAIT          /* `await expr` binds the entire expr to its right */
%start program
%type <Ast.program> program
%type <Ast.send_target> send_target
%%

program:
  | decls EOF { $1 }
  | error EOF { raise (Syntax_error (loc_of_rhs 1, "syntax error in program")) }
  
decls:
  | decl { [$1] }
  | decl SEMICOLON { [$1] }
  | decl SEMICOLON decls { $1 :: $3 }
  | decl decls { $1 :: $2 }

arg_list:
  expr                       { [$1] }
  | arg_list COMMA expr        { $1 @ [$3] }

decl:
  | CLASS ID LBRACE fields methods RBRACE  { Class { cname = $2; fields = $4; methods = $5 } }
  | CLASS ID LBRACE methods RBRACE         { Class { cname = $2; fields = []; methods = $4 } }
  | FUNCTION ID LPAREN annot_param_list RPAREN method_ret_opt LBRACE stmts RBRACE
      { let (names, tys) = List.split $4 in
        Function { fn_name = $2; fn_params = names; fn_param_types = tys;
                   fn_ret_ty = $6; fn_body = mk_stmt1 2 (Seq $8) } }
  | VAR ID ASSIGN expr SEMICOLON           { Global (mk_stmt1 2 (VarDecl ($2, $4))) }
  | VAR ID COLON type_expr ASSIGN expr SEMICOLON
      { Global (mk_stmt1 2 (TypedVarDecl ($2, $4, $6))) }
  | VAR ID dim_list SEMICOLON
      { Global (mk_stmt1 2 (VarDecl ($2, mk_expr1 3 (ArraySized ($3, None))))) }
  | VAR ID dim_list ASSIGN expr SEMICOLON
      { Global (mk_stmt1 2 (VarDecl ($2, mk_expr1 3 (ArraySized ($3, Some $5))))) }
  | ID ASSIGN expr SEMICOLON               { Global (mk_stmt1 1 (Assign ($1, $3))) }
  | SEND send_target DOT ID LPAREN args RPAREN SEMICOLON               { Global (mk_stmt1 1 (Send ($2, $4, $6))) }
  | UNSAFESEND send_target DOT ID LPAREN args RPAREN SEMICOLON         { Global (mk_stmt1 1 (UnsafeSend ($2, $4, $6))) }
  | ID LPAREN args RPAREN SEMICOLON        { Global (mk_stmt1 1 (CallStmt ($1, $3))) }

fields:
  | field { [$1] }
  | field fields { $1 :: $2 }

field:
  | FLOAT ID ASSIGN expr SEMICOLON { mk_stmt1 2  (VarDecl ($2, $4)) }
  | VAR ID ASSIGN expr SEMICOLON { mk_stmt1 2 (VarDecl ($2, $4)) }
  | VAR ID COLON type_expr ASSIGN expr SEMICOLON
      { mk_stmt1 2 (TypedVarDecl ($2, $4, $6)) }
  | VAR ID dim_list SEMICOLON
      { mk_stmt1 2 (VarDecl ($2, mk_expr1 3 (ArraySized ($3, None)))) }
  | VAR ID dim_list ASSIGN expr SEMICOLON
      { mk_stmt1 2 (VarDecl ($2, mk_expr1 3 (ArraySized ($3, Some $5)))) }
  
methods:
  | method_decl { [$1] }
  | method_decl methods { $1 :: $2 }

method_decl:
  | METHOD ID LPAREN annot_param_list RPAREN method_ret_opt LBRACE stmts RBRACE
    { let (names, tys) = List.split $4 in
      { mname = $2; params = names; param_types = tys; ret_ty = $6;
        body = mk_stmt1 2 (Seq $8) } }

annot_param:
  | ID                          { ($1, None) }
  | ID COLON type_expr          { ($1, Some $3) }

annot_param_list:
  |                                  { [] }
  | annot_param                      { [$1] }
  | annot_param COMMA annot_param_list { $1 :: $3 }

method_ret_opt:
  |                              { None }
  | ARROW type_expr              { Some $2 }

type_expr:
  | ID                                  { match $1 with
                                          | "int" -> TyEInt
                                          | "string" -> TyEString
                                          | "bool" -> TyEBool
                                          | "unit" -> TyEUnit
                                          | "any" -> TyEAny
                                          | n -> TyEName n }
  | FLOAT                               { TyEFloat }   /* `float` is a keyword token */
  | ID LBRACK type_expr RBRACK          { if $1 = "array" then TyEArray $3
                                          else TyEName ($1 ^ "[" ^ "...]") }
  | LPAREN type_expr_tuple RPAREN       { TyETuple $2 }
  | LBRACE type_expr_record RBRACE      { TyERecord $2 }
  | type_expr WHERE refine_or            { TyERefined ($1, $3) }
                                          /* O-2.a: T where <pred>
                                             — refinement, predicate
                                             stored in AST but not
                                             checked until O-2.b */

/* Refinement predicate sub-grammar.  Kept separate from `expr` so the
   AND_KW / OR_KW / NOT_KW tokens only carry boolean meaning when seen
   inside a `where` clause.  Same shape as Python's `refinement`. */
refine_or:
  | refine_and                                          { $1 }
  | refine_or OR_KW refine_and                          { RpBinop ("or", $1, $3) }
refine_and:
  | refine_not                                          { $1 }
  | refine_and AND_KW refine_not                        { RpBinop ("and", $1, $3) }
refine_not:
  | refine_cmp                                          { $1 }
  | NOT_KW refine_not                                   { RpUnary ("not", $2) }
refine_cmp:
  | refine_sum                                          { $1 }
  | refine_sum EQ refine_sum                            { RpBinop ("==", $1, $3) }
  | refine_sum NEQ refine_sum                           { RpBinop ("!=", $1, $3) }
  | refine_sum LT refine_sum                            { RpBinop ("<",  $1, $3) }
  | refine_sum GT refine_sum                            { RpBinop (">",  $1, $3) }
  | refine_sum LE refine_sum                            { RpBinop ("<=", $1, $3) }
  | refine_sum GE refine_sum                            { RpBinop (">=", $1, $3) }
refine_sum:
  | refine_mul                                          { $1 }
  | refine_sum PLUS refine_mul                          { RpBinop ("+", $1, $3) }
  | refine_sum MINUS refine_mul                         { RpBinop ("-", $1, $3) }
refine_mul:
  | refine_unary                                        { $1 }
  | refine_mul TIMES refine_unary                       { RpBinop ("*", $1, $3) }
  | refine_mul DIV refine_unary                         { RpBinop ("/", $1, $3) }
refine_unary:
  | MINUS refine_unary                                  { RpUnary ("-", $2) }
  | refine_atom                                         { $1 }
refine_atom:
  | INTLIT                                              { RpInt $1 }
  | FLOATLIT                                            { RpFloat $1 }
  | ID                                                  { RpVar $1 }
  | LPAREN refine_or RPAREN                             { RpParen $2 }

type_expr_tuple:
  | type_expr COMMA type_expr           { [$1; $3] }
  | type_expr COMMA type_expr_tuple     { $1 :: $3 }

type_expr_record:
  | ID COLON type_expr                       { [($1, $3)] }
  | ID COLON type_expr COMMA type_expr_record { ($1, $3) :: $5 }

dim_list:
  | LBRACK expr RBRACK            { [$2] }
  | LBRACK expr RBRACK dim_list   { $2 :: $4 }

send_target:
    ID                                                { LocalTarget $1 }
  | REMOTE LPAREN STRINGLIT COMMA STRINGLIT RPAREN    { RemoteTarget ($3, $5) }

stmts:
  | stmt { [$1] }
  | stmt stmts { $1 :: $2 }

stmt_list:
  | stmt stmt_list { $1::$2 }
  |                { [] }
  
stmt:
  | ID ASSIGN expr SEMICOLON { mk_stmt1 1 (Assign ($1, $3)) }
  | CALL ID LPAREN args RPAREN SEMICOLON { mk_stmt1 2 (CallStmt ($2, $4)) }
  | SEND SELF DOT ID LPAREN args RPAREN SEMICOLON { mk_stmt1 4 (Send(LocalTarget "self", $4, $6)) }
  | SEND SENDER DOT ID LPAREN args RPAREN SEMICOLON { mk_stmt1 4 (Send (LocalTarget "sender", $4, $6)) }
  | SEND send_target DOT ID LPAREN args RPAREN SEMICOLON { mk_stmt1 2 (Send ($2, $4, $6)) }
  | UNSAFESEND send_target DOT ID LPAREN args RPAREN SEMICOLON { mk_stmt1 2 (UnsafeSend ($2, $4, $6)) }
  | IF LPAREN expr RPAREN stmt           %prec IFX { mk_stmt1 2 (If($3, $5, mk_stmt1 5 (Seq([])))) }
  | IF LPAREN expr RPAREN stmt ELSE stmt           { mk_stmt1 3 (If($3, $5, $7)) }
  | WHILE expr DO stmt { mk_stmt1 2 (While ($2, $4)) }
  | LBRACE stmt_list RBRACE { mk_stmt1 2 (Seq $2) }
  | VAR ID ASSIGN expr SEMICOLON { mk_stmt1 2 (VarDecl($2, $4)) }
  | VAR ID COLON type_expr ASSIGN expr SEMICOLON
      { mk_stmt1 2 (TypedVarDecl($2, $4, $6)) }
  | VAR ID dim_list SEMICOLON
      { mk_stmt1 2 (VarDecl($2, mk_expr1 3 (ArraySized($3, None)))) }
  | VAR ID dim_list ASSIGN expr SEMICOLON
      { mk_stmt1 2 (VarDecl($2, mk_expr1 3 (ArraySized($3, Some $5)))) }
  | ID LPAREN args RPAREN SEMICOLON { mk_stmt1 1 (CallStmt ($1, $3)) }
  | BECOME ID LPAREN args RPAREN SEMICOLON { mk_stmt1 2 (Become ($2, $4)) }
  | SELECT LBRACE select_cases select_timeout_opt RBRACE { mk_stmt1 3 (Select($3, $4)) }
  | RETURN expr SEMICOLON                              { mk_stmt1 1 (Return (Some $2)) }
  | RETURN SEMICOLON                                   { mk_stmt1 1 (Return None) }

select_cases:
    select_cases select_case { $1 @ [$2] }
  | /* empty */              { [] }

select_case:
  CASE select_pat ARROW LBRACE stmts RBRACE
    { { pat = $2; body = mk_stmt1 5 (Seq($5)) } }

select_pat:
  ID LPAREN opt_id_list RPAREN
    { { meth = $1; vars = $3 } }

opt_id_list:
    id_list { $1 }
  | /* empty */ { [] }

id_list:
    ID                   { [$1] }
  | id_list COMMA ID  { $1 @ [$3] }

select_timeout_opt:
    TIMEOUT INTLIT ARROW LBRACE stmts RBRACE
      { (Some $2, Some (mk_stmt1 5 (Seq $5))) }
  | /* empty */
      { (None, None) }

args:
  /* empty */    { [] }
  | arg_list     { $1 }

expr:
  | FLOATLIT { mk_expr1 1 (Float $1) }
  | STRINGLIT { mk_expr1 1 (String $1) }
  | INTLIT { mk_expr1 1 (Int $1) }
  | ID { mk_expr1 1 (Var $1) }
  | SELF { mk_expr1 1 (Var "self") }
  | SENDER { mk_expr1 1 (Var "sender") }
  | expr PLUS expr { mk_expr1 2 (Binop ("+", $1, $3)) }
  | expr MINUS expr { mk_expr1 2 (Binop ("-", $1, $3)) }
  | expr TIMES expr { mk_expr1 2 (Binop ("*", $1, $3)) }
  | expr DIV expr { mk_expr1 2 (Binop ("/", $1, $3)) }
  | NEW ID LPAREN args RPAREN { mk_expr1 1 (New ($2, $4)) }
  | ID LPAREN args RPAREN { mk_expr1 1 (Call ($1, $3)) }
  | expr GE expr { mk_expr1 2 (Binop (">=", $1, $3)) }
  | expr LE expr { mk_expr1 2 (Binop ("<=", $1, $3)) }
  | expr GT expr { mk_expr1 2 (Binop (">", $1, $3)) }
  | expr LT expr { mk_expr1 2 (Binop ("<", $1, $3)) }
  | expr EQ  expr { mk_expr1 2 (Binop ("==", $1, $3)) }
  | expr NEQ expr { mk_expr1 2 (Binop ("!=", $1, $3)) }
  | LPAREN expr RPAREN { $2 }
  | LPAREN expr COMMA arg_list RPAREN             { mk_expr1 1 (TupleLit ($2 :: $4)) }
  | LBRACE record_fields RBRACE                   { mk_expr1 1 (RecordLit $2) }
  | expr DOT ID                                   { mk_expr1 2 (FieldAccess ($1, $3)) }
  | expr LBRACK INTLIT RBRACK                     { mk_expr1 2 (IndexExpr ($1, $3)) }
  | NOW send_target DOT ID LPAREN args RPAREN     { mk_expr1 1 (Now ($2, $4, $6)) }
  | FUTURE send_target DOT ID LPAREN args RPAREN  { mk_expr1 1 (Future ($2, $4, $6)) }
  | AWAIT expr %prec UAWAIT                       { mk_expr1 1 (Await $2) }

record_fields:
  | ID COLON expr                       { [($1, $3)] }
  | ID COLON expr COMMA record_fields   { ($1, $3) :: $5 }
