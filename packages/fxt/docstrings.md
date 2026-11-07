

# USE GOOGLE SYNTAX FOR NOW

for more examples, see:
    https://www.sphinx-doc.org/en/master/usage/extensions/example_google.html

notes:
- you can put the types in the docstring OR put the types in the function def
  -> if you put them in the function def you don't need to put them in the docstring


```py
def function_with_pep484_type_annotations(param1: int, param2: str) -> bool:
    """Example function with PEP 484 type annotations.

    Args:
        param1: The first parameter.
        param2: The second parameter.

    Returns:
        The return value. True for success, False otherwise.

    """




```



