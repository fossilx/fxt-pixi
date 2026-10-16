

Create a subdir for each custom module:

	mkdir fxt
	cd fxt

Then create an empty python package using pixi:

	pixi init --format pyproject


This will create the correct directory structure. In this case (with `fxt`), 
it created:


	./fxt
		/src
			/fxt
				__init__.py
		/.gitignore
		/.gitattributes
		/pyproject.toml

Example from claude:

```
	~/dev/.jupyter-pixi/
	├── pixi.toml
	├── jupyter/              # notebooks, root dir for JupyterLab
	├── src/
	│   ├── custom_module_1/
	│   │   ├── pyproject.toml
	│   │   └── custom_module_1/
	│   │       └── __init__.py
	│   └── custom_module_2/
	│       ├── pyproject.toml
	│       └── custom_module_2/
	│           └── __init__.py
```

Each project needs a minimal pyproject file. Pixi generates on for you.

------------------------------------------------------------------------------


Then, to get the local pixi install to recognize it, you add the following
to your `pixi.toml` file:


```toml
[pypi-dependencies]
fxt = { path = "./src/fxt" }
```

Lastly, run `pixi install` and pixi sets up the needed links/etc.


------------------------------------------------------------------------------

You should now be able to `import fxt`
