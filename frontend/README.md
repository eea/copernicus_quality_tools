# QC Tool USER-FACING application
Steps to install the code and run it
```
git clone https://github.com/eea/copernicus_quality_tools
cd copernicus_quality_tools
git checkout ui
cd frontend/django/qctool
python3 -m venv env
source env/bin/activate
pip install -r requirements.txt
python manage.py runserver
```
