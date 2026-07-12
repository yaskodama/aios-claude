#!/usr/bin/env python3
"""mecharm_rl.py — 6軸アーム(elephant robotics mecharm 相当)の到達動作を、
方策探索型強化学習(CEM: Cross-Entropy Method)で滑らかに学習するシミュレーション。
numpy 非依存(pure Python)。

  ・状態 s = 目標手先位置(3D)。方策 π_φ: s -> 目標関節角 qstar(6) の線形写像 + 関節ゲイン K(6)。
    これは学習される簡易 IK + 制御ゲインであり、TinyML の小型方策(RL で学習)に対応する。
  ・各ステップ: 関節速度 v_j = clip(K_j*(qstar_j - q_j))、q を積分して手先を FK で得る。
  ・報酬 = -(到達誤差) - λj*(ジャーク総和) - λo*(オーバーシュート)。
  ・CEM(母集団サンプル→エリート→平均/分散更新)で方策パラメータ φ を最適化。
  ・世代ごとに 到達誤差[cm]・ジャーク・成功率 を記録し、学習で滑らかかつ正確になることを示す。
"""
import math, random, csv, pathlib

BASE_H = 0.06
L = [0.10, 0.096, 0.066, 0.073, 0.0456]   # mecharm 相当リンク長[m]
DT = 0.02; T = 120; JLIM = math.radians(160); REACH_TOL = 0.04  # 成功=4cm以内

def fk(q):
    a=0.0; xr=0.0; z=BASE_H
    for i in range(4):
        a+=q[1+i]; xr+=L[i]*math.cos(a); z+=L[i]*math.sin(a)
    a+=q[5]; xr+=L[4]*math.cos(a); z+=L[4]*math.sin(a)
    return (xr*math.cos(q[0]), xr*math.sin(q[0]), z)

def dist(p,t): return math.sqrt((p[0]-t[0])**2+(p[1]-t[1])**2+(p[2]-t[2])**2)

# ---- 目標条件付き方策 φ = [W(6x3=18), b(6), gain(6)] = 30 次元 ----
def policy_qstar(phi, s):
    W=phi[:18]; b=phi[18:24]
    q=[0.0]*6
    for j in range(6):
        q[j]=b[j]+W[j*3+0]*s[0]+W[j*3+1]*s[1]+W[j*3+2]*s[2]
        q[j]=max(-JLIM,min(JLIM,q[j]))
    return q
def policy_gain(phi):
    return [max(0.5,g) for g in phi[24:30]]

def rollout(phi, target):
    qstar=policy_qstar(phi,target); K=policy_gain(phi)
    q=[0.0]*6; prevv=[0.0]*6; jerk=0.0; over=0.0
    for _ in range(T):
        v=[0.0]*6
        for j in range(6):
            e=qstar[j]-q[j]; vj=max(-4.0,min(4.0,K[j]*e)); v[j]=vj
            q[j]=max(-JLIM,min(JLIM,q[j]+vj*DT)); jerk+=abs(vj-prevv[j])
            if (qstar[j]-q[j])*e<0: over+=abs(qstar[j]-q[j])
        prevv=v
    return dist(fk(q),target), jerk, over

def reward(phi,target,lj=0.05,lo=1.0):
    d,jk,ov=rollout(phi,target); return -(d)-lj*jk*DT-lo*ov, d, jk

# ---- 到達可能な作業空間からランダム目標(前方・中高さ) ----
def sample_target(rng):
    q=[rng.uniform(-1.0,1.0), rng.uniform(-0.7,0.4), rng.uniform(-1.4,-0.2),
       rng.uniform(-0.9,0.3), rng.uniform(-0.6,0.6), 0.0]
    return fk(q)

def main():
    rng=random.Random(7); D=30
    mean=[0.0]*24+[4.0]*6; std=[0.5]*18+[0.4]*6+[2.0]*6
    POP,ELITE,GEN,NTASK=48,10,120,8
    rows=[]
    for g in range(GEN):
        tasks=[sample_target(rng) for _ in range(NTASK)]
        pop=[]
        for _ in range(POP):
            p=[mean[k]+std[k]*rng.gauss(0,1) for k in range(D)]
            sc=0.0
            for tg in tasks: r,_,_=reward(p,tg); sc+=r
            pop.append((sc/NTASK,p))
        pop.sort(key=lambda x:-x[0]); elite=[e[1] for e in pop[:ELITE]]
        for k in range(D):
            vals=[e[k] for e in elite]; m=sum(vals)/len(vals)
            var=sum((x-m)**2 for x in vals)/len(vals)
            mean[k]=m; std[k]=max(0.03,math.sqrt(var))
        # 固定 20 目標で現方策(mean)を評価
        ev=[sample_target(random.Random(1000+t)) for t in range(20)]
        errs=[]; jks=[]; succ=0
        for tg in ev:
            d,jk,ov=rollout(mean,tg); errs.append(d); jks.append(jk*DT)
            if d<=REACH_TOL: succ+=1
        me=100*sum(errs)/len(errs); mj=sum(jks)/len(jks); sr=100*succ/len(ev)
        rows.append((g,round(me,2),round(mj,3),round(sr,1)))
        if g%10==0 or g==GEN-1:
            print(f"gen {g:3d}  到達誤差 {me:6.2f} cm  ジャーク {mj:6.2f}  成功率 {sr:5.1f}%")
    out=pathlib.Path(__file__).resolve().parent/"results.csv"
    with open(out,"w",newline="") as f:
        w=csv.writer(f); w.writerow(["gen","err_cm","jerk","success_pct"]); w.writerows(rows)
    r0,rN=rows[0],rows[-1]
    print(f"\n=== 学習前 -> 学習後 ===\n到達誤差 {r0[1]}cm -> {rN[1]}cm | ジャーク {r0[2]} -> {rN[2]} | 成功率 {r0[3]}% -> {rN[3]}%")
    print("results.csv written")

if __name__=="__main__": main()
