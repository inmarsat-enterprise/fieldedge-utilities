#!/bin/bash
pdoc --html fieldedge_utilities --output-dir docs --force
mv ./docs/fieldedge_utilities/* ./docs
rm -r ./docs/fieldedge_utilities
