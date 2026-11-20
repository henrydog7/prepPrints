# prepPrints
process 3d prints from D2L download for APSC 101



should just need to select all groups in print addignment page, download big zip and extract, move python file (prepPrint.py) into that folder and then double click to run.

may need to install python here https://www.python.org/

if double click does not work open terminal in folder and run

this has been tested for windows

```
python prepPrints.py
```


may also need to 

```
python -m pip install pillow numpy
```

finally if that does not work try this or email 21lrb9@queensu.ca
windows:
```
python -m venv .venv
\.venv\scripts\activate
pip install pillow numpy
```

mac/linux: (untested)
```
python -m venv .venv
source /.venv/bin/activate
pip install pillow numpy
```
