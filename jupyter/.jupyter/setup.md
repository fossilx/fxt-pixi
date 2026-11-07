
# jupyter-pixi setup

I moved this to a project-level install of jupyter (instead of using a global install). This should help keep everything together and the results reproducible.

This is meant to be run within a pixi environment with a fairly specific setup. I will try to detail the setup so that you can change how it is configured if you so desire.

## core use

To start jupyter, you can use the following pixi task:

```toml
lab = "python jupyter/.jupyter/launcher.py"
```

Aka run:
`pixi run lab`



## core files

- `launcher.py`
  
  runs jupyter for you, makes whatever changes you need (ie env vars)

- `jupyter_lab_config.py`
  
  the default name of the jupyter-lab config. it is loaded automatically from
  within the jupyter config dir. This is where most important config options sit.

- `custom\custom.css`
  
  this file is used to provide custom css to the jupyter-lab environment. this 
  is so I can have access to custom css classes within the markdown cells. 

  the main reason I use this is so I can have custom `<hr>` styles that I can
  **EASILY SEE** when using dark-mode. the default rendering for horizontal rules
  is....bad. I also added support for colored spans using the same set of colors.

  for example:
  ```css
  hr.blue { border-width: 2px; border-style: solid; border-color: #58a6ff; }
  hr.yellow { border-width: 2px; border-style: solid; border-color: #ffd380; }
  hr.orange { border-width: 2px; border-style: solid; border-color: #ff8531; }
  ...
  span.blue, p.blue { color: #58a6ff; }
  span.yellow, p.yellow { color: #ffd380; }
  span.orange, p.orange { color: #ff8531; }
  ...
  ```



## path components

> note: `root` corresponds to the root of the pixi project

- **jupyter root** (where the file browser starts): 
  ```
  root/jupyter
  ```

- **jupyter configuration**
  > note: i use python for most config options
  ```
  root/jupyter/.jupyter
  ```

  - the main config dir is now within the project. this overrides the default
    config dir that is traditionally in the user's home dir. 
    
  - This is set in the launcher by setting the env variable:
    `JUPYTER_CONFIG_DIR`

  - The config is stored in a `.jupyter` dir within the `jupyter-root`, aka:
    `root/jupyter/.jupyter`
  
  - The basic process of setting the env var:
    ```py
    import os
    import pathlib
    #pixi sets this env var when you use pixi run/shell
    root:Path = Path(os.environ.get("PIXI_PROJECT_ROOT"))
    #get current env, add entry for jupyter config (as a str!)
    env:dict[str,str] = os.environ.copy()
    env["JUPYTER_CONFIG_DIR"] = str(root / "jupyter" / ".jupyter")
    ```
    You then send the `env` dict to `subprocess.run(..., env=env)` when
    spawning the jupyter process.


## jupyter config options

The options I set..

- via the **config**:
  - the server root dir, aka the "notebook dir". this is where the file 
    browser starts

  - the password hash (to allow entry) 

- via the command:
  - `--no-browser`
    stops the browser from auto-running cuz that's annoying
  - `--custom-css`
    tells it to load the custom css we have setup within the jupyter 
    config dir



# mods

### core
- `pixi-kernel`
  
  assuming you execute this within a pixi project, this should allow you to select the nearest version of pixi for you python kernel.


### output related
> I will probably add more, but only if/as I need them.

- `bokeh-jupyter-bokeh`

- re: `jupyterlab-plotly` — as long as you have a newer version of jupyterlab (3+) you don't need an extension anymore



### utils/nice to have
- `jupyterlab-execute-time` — [@github](https://github.com/deshaw/jupyterlab-execute-time)
  - `pixi add jupyterlab_execute_time --pypi`


### may add in the future:
- `jupyterlab-myst` — [@github](https://github.com/jupyter-book/jupyterlab-myst))

  this adds support for `MyST` markdown...which is a hybrid of `markdown` + `reStructuredText`. i had issues with it initially though so I haven't bothered figuring out wtf is wrong.



- jupyter_pixi or w/e it is called that let's you pick the local pixi copy
  of python as the kernel
 
- jupyter_myst
  looks interesting but haven't gotten it to work yet
 
- execution time
  





## if you want a custom config...

I suggest creating that python config within the jupyter config dir. 

For example, at:

```
root/jupyter/.jupyter/custom-conf.py
```

Then, go to the launcher and simply tell it to use your config file 
by modifying the `cmd` list.

> note: you don't need to include `pixi run` in this if i understand 
> correctly. i think this is because pixi is already running this copy
> of python. the command is basically what you'd use if you were defining
> a pixi task.

```py
    cmd: list[str] = [
        "jupyter", "lab",
        "--no-browser",
        "--custom-css",
    ]
```
to..
```py
    cmd: list[str] = [
        "jupyter", "lab",
        "--no-browser",
        "--custom-css",
        #f"--config={config}",
    ]
```

