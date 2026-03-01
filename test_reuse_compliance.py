#!/usr/bin/env python3
"""Test REUSE compliance for luskctl project."""

import os
import subprocess
import tempfile
from pathlib import Path

def test_reuse_compliance():
    """Test REUSE compliance by creating a temporary directory with only project files."""
    
    # Create temporary directory
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        # Copy project structure to temp directory
        project_files = [
            'LICENSES',
            'REUSE.toml',
            'src',
            'docs',
            'tests',
            'examples',
            'completions',
            'pyproject.toml',
            'README.md',
            '.github'
        ]
        
        for item in project_files:
            src_path = Path(f"/workspace/{item}")
            if src_path.exists():
                if src_path.is_dir():
                    # Copy directory
                    dest_dir = temp_path / item
                    dest_dir.mkdir(exist_ok=True)
                    for root, dirs, files in os.walk(src_path):
                        for file in files:
                            src_file = Path(root) / file
                            rel_path = src_file.relative_to(src_path)
                            dest_file = dest_dir / rel_path
                            dest_file.parent.mkdir(parents=True, exist_ok=True)
                            with open(src_file, 'r') as f_src, open(dest_file, 'w') as f_dest:
                                f_dest.write(f_src.read())
                else:
                    # Copy file
                    with open(src_path, 'r') as f_src:
                        content = f_src.read()
                    with open(temp_path / item, 'w') as f_dest:
                        f_dest.write(content)
        
        # Run reuse lint in temp directory
        print(f"Testing REUSE compliance in {temp_dir}")
        result = subprocess.run(
            ['reuse', 'lint'],
            cwd=temp_dir,
            capture_output=True,
            text=True
        )
        
        print("STDOUT:")
        print(result.stdout)
        print("STDERR:")
        print(result.stderr)
        print(f"Return code: {result.returncode}")
        
        return result.returncode == 0

if __name__ == "__main__":
    success = test_reuse_compliance()
    if success:
        print("✓ REUSE compliance test passed!")
    else:
        print("✗ REUSE compliance test failed!")
    exit(0 if success else 1)