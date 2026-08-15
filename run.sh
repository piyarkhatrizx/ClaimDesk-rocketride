#!/bin/bash
pip install -r requirements.txt
python serve.py
#!/bin/bash
sed -i '' '/"reasoning_effort"/d' pipelines/claim-processor.pipe
pip install -r requirements.txt
python serve.py