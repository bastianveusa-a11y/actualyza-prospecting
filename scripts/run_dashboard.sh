#!/bin/bash
cd /Users/Bastian/scrapy/actualyza-prospecting
echo ""
echo "  Iniciando Actualyza Dashboard…"
echo "  → http://localhost:5055"
echo ""
open "http://localhost:5055" &
sleep 1
/usr/bin/python3 dashboard/app.py
