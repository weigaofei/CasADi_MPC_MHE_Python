#!/usr/bin/env python
# -*- coding: utf-8 -*-

import casadi as ca
import casadi.tools as ca_tools

import numpy as np
from draw import Draw_MPC_Obstacle

def shift_movement(T, t0, x0, u, f):
    print('u0:{}'.format(u[:, 0]))
    f_value = f(x0, u[:, 0])
    print('{0}, {1}'.format(t0, f_value))
    st = x0 + T*f_value
    t = t0 + T
    u_end = ca.horzcat(u[:, 1], u[:, :-1])
    print('{0}, uend {1}'.format(t0, u_end))
    return t, st, u_end

if __name__ == '__main__':
    T = 0.2 # sampling time [s]
    N = 100 # prediction horizon
    rob_diam = 0.3 # [m]
    v_max = 0.6
    omega_max = np.pi/4.0

    states = ca_tools.struct_symSX([
        (
            ca_tools.entry('x'),
            ca_tools.entry('y'),
            ca_tools.entry('theta')
        )
    ])
    x, y, theta = states[...]
    n_states = states.size

    controls  = ca_tools.struct_symSX([
        (
            ca_tools.entry('v'),
            ca_tools.entry('omega')
        )
    ])
    v, omega = controls[...]
    n_controls = controls.size

    ## rhs
    rhs = ca_tools.struct_SX(states)
    rhs['x'] = v*np.cos(theta)
    rhs['y'] = v*np.sin(theta)
    rhs['theta'] = omega

    ## function
    f = ca.Function('f', [states, controls], [rhs], ['input_state', 'control_input'], ['rhs'])

    ## for MPC multi shooting
    optimizing_target = ca_tools.struct_symSX([
        (
            ca_tools.entry('U', repeat=N, struct=controls),
            ca_tools.entry('X', repeat=N+1, struct=states)
        )
    ])
    U, X, = optimizing_target[...] # data are stored in list [], notice that ',' cannot be missed

    current_parameters = ca_tools.struct_symSX([
        (
            ca_tools.entry('P', shape=n_states+n_states),
        )
    ])
    P, = current_parameters[...]

    ### define
    Q = np.array([[1.0, 0.0, 0.0],[0.0, 5.0, 0.0],[0.0, 0.0, .1]])
    R = np.array([[0.5, 0.0], [0.0, 0.05]])
    #### cost function
    obj = 0 #### cost
    #### constrains
    g = [] # equal constrains
    lbg = []
    ubg = []
    g.append(X[0]-P[:3]) # initial condition constraints 
    for i in range(N):
        obj = obj + ca.mtimes([(X[i]-P[3:]).T, Q, X[i]-P[3:]]) + ca.mtimes([U[i].T, R, U[i]])
        x_next_ = f(X[i], U[i])*T + X[i]
        g.append(X[i+1] - x_next_)
    #### obstacle definition
    obs_x = 0.5
    obs_y = 0.5
    obs_diam = 0.3
    ##### add constraints to obstacle distance
    for i in range(N+1):
        g.append(np.sqrt((X[i][0]-obs_x)**2+(X[i][1]-obs_y)**2)-(rob_diam/2.+obs_diam/2.))


    nlp_prob = {'f': obj, 'x': optimizing_target, 'p':current_parameters, 'g':ca.vertcat(*g)}
    opts_setting = {'ipopt.max_iter':100, 'ipopt.print_level':0, 'print_time':0, 'ipopt.acceptable_tol':1e-8, 'ipopt.acceptable_obj_change_tol':1e-6}

    solver = ca.nlpsol('solver', 'ipopt', nlp_prob, opts_setting)

    lbx = []
    ubx = []

    ## add constraints for equations
    for _ in range(N+1):
        lbg.append(0.0)
        ubg.append(0.0)
        lbg.append(0.0)
        ubg.append(0.0)
        lbg.append(0.0)
        ubg.append(0.0)
    for _ in range(N+1):
        lbg.append(-0.01)
        ubg.append(np.inf)

    ## add constraints to control and states notice that for the N+1 th state
    for _ in range(N):
        lbx.append(-v_max)
        lbx.append(-omega_max)
        ubx.append(v_max)
        ubx.append(omega_max)
        lbx.append(-2.0)
        lbx.append(-2.0)
        lbx.append(-np.inf)
        ubx.append(2.0)
        ubx.append(2.0)
        ubx.append(np.inf)
    # for the N+1 state
    lbx.append(-2.0)
    lbx.append(-2.0)
    lbx.append(-np.inf)
    ubx.append(2.0)
    ubx.append(2.0)
    ubx.append(np.inf)

    # Simulation
    t0 = 0.0
    x0 = np.array([0.0, 0.0, 0.0]).reshape(-1, 1)# initial state
    x0_ = x0.copy()
    xs = np.array([1.5, 1.5, 0.0]).reshape(-1, 1) # final state
    u0 = np.array([0.0, 0.0]*N).reshape(-1, 2).T# np.ones((N, 2)) # controls
    ff_value = np.array([0.0, 0.0, 0.0]*(N+1)).reshape(-1, 3).T
    x_c = [] # contains for the history of the state
    u_c = []
    t_c = [t0] # for the time
    xx = []
    sim_time = 20.0

    ## start MPC
    mpciter = 0
    ### inital test
    c_p = current_parameters(0)
    init_control = optimizing_target(0)
    # print(u0.shape) u0 should have (n_controls, N)
    while(np.linalg.norm(x0-xs)>1e-2 and mpciter-sim_time/T<0.0 and mpciter<10):
        ## set parameter
        # print('x0 {}'.format(x0))
        c_p['P'] = np.concatenate((x0, xs))
        init_control['X', lambda x:ca.horzcat(*x)] = ff_value[:, 0:N+1] 
        init_control['U', lambda x:ca.horzcat(*x)] = u0[:, 0:N]
        # print("run {0}\n {1}".format(mpciter, u0.T))
        res = solver(x0=init_control, p=c_p, lbg=lbg, lbx=lbx, ubg=ubg, ubx=ubx)
        estimated_opt = res['x'].full() # the feedback is in the series [u0, x0, u1, x1, ...]
        ff_last_ = estimated_opt[-3:]
        temp_estimated = estimated_opt[:-3].reshape(-1, 5)
        u0 = temp_estimated[:, :2].T
        # print("run after {0}\n {1}".format(mpciter, u0.T))
        ff_value = temp_estimated[:, 2:].T
        ff_value = np.concatenate((ff_value, estimated_opt[-3:].reshape(3, 1)), axis=1) # add the last estimated result now is n_states * (N+1)
        # print("run after trajectory {}".format(ff_value.T))
        x_c.append(ff_value)
        u_c.append(u0[:, 0])
        t_c.append(t0)
        t0, x0, u0 = shift_movement(T, t0, x0, u0, f)
        x0 = ca.reshape(x0, -1, 1)
        xx.append(x0.full())
        mpciter = mpciter + 1

    print(mpciter)
    draw_result = Draw_MPC_Obstacle(rob_diam=0.3, init_state=x0_, target_state=xs, robot_states=xx, obstacle=np.array([obs_x, obs_y, obs_diam/2.]), export_fig=False)