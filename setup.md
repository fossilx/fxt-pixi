

# re: jupyter

**notes**

- This is setup to **run jupyter** from a global pixi install.

- The benefits of this setup:
  a. the jupyter shell and it's settings -- ie: access password, theme, etc --
     stay the same across projects.
  b. 

- The kernels however, will be loaded from the local directory.

- internals:
  - this installs packages into **global environments**, and exposes their 
    command-line apps.
  - so, for jupyterlab, I created an environment called "jupyterlab" and
    installed jupyterlab within it.


**refs**
- https://pixi.prefix.dev/latest/reference/cli/pixi/global/

- the install command i assume was something like:
      
      `pixi global install jupyterlab --environment jupyterlab`


### commands

**list the envs, their deps, and the terminal cmds they expose**
> https://pixi.prefix.dev/latest/reference/cli/pixi/global/list/
```sh
➜  ~ pixi global list
Global environments as specified in '/home/tony/.pixi/manifests/pixi-global.toml'
├── direnv: 2.37.1 
│   └─ exposes: direnv
├── jupyterlab 
│   ├─ dependencies: jupyterlab 4.6.0, pixi-kernel 0.7.1, pip 26.1.2
│   └─ exposes: jupyter-lab, jupyter-labextension, jupyter-labhub
└── pixi-kernel: 0.7.1 
    └─ exposes: Nothing
```

**list the packages in a specific env**
> https://pixi.prefix.dev/latest/reference/cli/pixi/global/list/
> this is similar to `pixi list`
```sh
➜  ~ pixi global list --environment jupyterlab
```


**update an env**
> https://pixi.prefix.dev/latest/reference/cli/pixi/global/update/
```sh
➜  ~ pixi global update jupyterlab
✔ Updated packages in environment jupyterlab.
    - jupyterlab 4.6.0 -> 4.6.4
    - pip 26.1.2 -> 26.2.1
    - pixi-kernel 0.7.1 -> 0.7.1 
```

