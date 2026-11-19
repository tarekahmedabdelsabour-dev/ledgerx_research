# Install

```bash
cd ~/frappe-bench-v16
git clone <repo-url> apps/ledgerx_research
echo "" >> sites/apps.txt && echo "ledgerx_research" >> sites/apps.txt
./env/bin/pip install numpy scipy
./env/bin/pip install -e apps/ledgerx_research
ln -sfn ~/frappe-bench-v16/apps/ledgerx_research/ledgerx_research/public sites/assets/ledgerx_research
bench --site mysite.localhost install-app ledgerx_research
bench --site mysite.localhost migrate
bench --site mysite.localhost clear-cache
```
Then restart and hard-refresh the browser (Ctrl+Shift+R).

Check the solver: `./env/bin/python -c "import scipy; print(scipy.__version__)"`.
