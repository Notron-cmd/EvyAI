import os
import re
import subprocess
import threading
import difflib
import json
from pathlib import Path
from datetime import datetime

import win32gui
import win32process
import psutil


class WorkspaceDetector:
    def __init__(self):
        self.vscode_processes = []
    
    def get_active_workspace(self) -> Path | None:
        """
        Try multiple detection methods in sequence:
        1. Window title (most reliable for single-folder setup)
        2. VS Code process priority (no limit, filter AppData)
        3. General process detection (fallback, limit 500)
        """
        print("[WorkspaceDetector] Starting workspace detection...")
        
        # Method 1: Window title (primary - most reliable)
        workspace = self._detect_from_window_title()
        if workspace:
            print(f"[WorkspaceDetector] [OK] Detected via window title: {workspace}")
            return workspace
        
        # Method 2: VS Code processes (secondary - prioritized, no limit)
        workspace = self._detect_from_vscode_processes()
        if workspace:
            print(f"[WorkspaceDetector] [OK] Detected via VS Code process: {workspace}")
            return workspace
        
        # Method 3: General process detection (fallback)
        workspace = self.detect_from_process()
        if workspace:
            print(f"[WorkspaceDetector] [OK] Detected via general process scan: {workspace}")
            return workspace
        
        print("[WorkspaceDetector] [FAIL] No VS Code workspace detected")
        return None
    
    def _detect_from_window_title(self) -> Path | None:
        """
        Scan all visible VS Code windows using EnumWindows.
        Parse both title formats:
        - "foldername - Visual Studio Code"
        - "filename - foldername - Visual Studio Code"
        Prioritize active/focused window first.
        """
        results = []
        
        try:
            # Get active window first (highest priority)
            active_hwnd = win32gui.GetForegroundWindow()
            if active_hwnd:
                active_title = win32gui.GetWindowText(active_hwnd)
                if active_title and "Visual Studio Code" in active_title:
                    workspace = self._parse_vscode_title(active_title)
                    if workspace:
                        results.insert(0, workspace)  # Highest priority
            
            # Scan all visible windows
            def callback(hwnd, _):
                if win32gui.IsWindowVisible(hwnd):
                    title = win32gui.GetWindowText(hwnd)
                    if title and "Visual Studio Code" in title:
                        # Skip if already added as active window
                        if hwnd != active_hwnd:
                            workspace = self._parse_vscode_title(title)
                            if workspace:
                                results.append(workspace)
            
            win32gui.EnumWindows(callback, None)
            
            return results[0] if results else None
            
        except Exception as e:
            print(f"[WorkspaceDetector] Window title detection error: {e}")
            return None
    
    def _parse_vscode_title(self, title: str) -> Path | None:
        """
        Parse VS Code window title to extract folder name.
        Formats:
        - "foldername - Visual Studio Code"
        - "filename - foldername - Visual Studio Code"
        """
        if "Visual Studio Code" not in title:
            return None
        
        parts = title.split(" - ")
        
        # Format: "filename - foldername - Visual Studio Code"
        if len(parts) >= 3:
            folder_name = parts[-2].strip()
            return self._resolve_workspace(folder_name)
        
        # Format: "foldername - Visual Studio Code"
        elif len(parts) >= 2:
            folder_name = parts[0].strip()
            return self._resolve_workspace(folder_name)
        
        return None
    
    def _detect_from_vscode_processes(self) -> Path | None:
        """
        Collect ALL VS Code processes (no limit).
        Filter out AppData directories (VS Code installation).
        Return first valid workspace path.
        """
        vscode_procs = []
        
        try:
            # Collect all VS Code processes (no limit)
            for proc in psutil.process_iter(['pid', 'name']):
                if 'Code.exe' in proc.info.get('name', ''):
                    vscode_procs.append(proc)
            
            print(f"[WorkspaceDetector] Found {len(vscode_procs)} VS Code processes")
            
            # Try each process
            for proc in vscode_procs:
                try:
                    cwd = Path(proc.cwd())
                    
                    # Skip if doesn't exist
                    if not cwd.exists():
                        continue
                    
                    # Skip AppData directories (VS Code installation)
                    cwd_str = str(cwd)
                    if "AppData" in cwd_str:
                        continue
                    
                    return cwd
                    
                except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                    continue
                except Exception as e:
                    print(f"[WorkspaceDetector] Error accessing process {proc.pid}: {e}")
                    continue
            
            return None
            
        except Exception as e:
            print(f"[WorkspaceDetector] VS Code process detection error: {e}")
            return None
    
    def _resolve_workspace(self, folder_name: str) -> Path | None:
        """
        Resolve folder name to actual workspace path.
        Check common locations first, then fallback to process matching.
        """
        folder_name_lower = folder_name.lower()
        
        # Common paths where user projects are stored
        common_paths = [
            Path.home() / "Documents" / folder_name,
            Path.home() / folder_name,
            Path("C:/Users") / os.getenv("USERNAME") / folder_name,
        ]
        
        # Check common paths first (fastest)
        for path in common_paths:
            if path.exists() and path.is_dir():
                return path
        
        # Fallback: scan VS Code processes for matching cwd
        try:
            vscode_procs = []
            for proc in psutil.process_iter(['pid', 'name']):
                if 'Code.exe' in proc.info.get('name', ''):
                    vscode_procs.append(proc)
            
            for proc in vscode_procs:
                try:
                    cwd = Path(proc.cwd())
                    cwd_str = str(cwd)
                    
                    # Skip AppData directories (VS Code installation)
                    if "AppData" in cwd_str:
                        continue
                    
                    # Check if folder name matches
                    if folder_name_lower in cwd_str.lower():
                        return cwd
                        
                except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                    continue
                    
        except Exception as e:
            print(f"[WorkspaceDetector] Process scan error in _resolve_workspace: {e}")
        
        return None
    
    def detect_from_process(self) -> Path | None:
        """
        General process detection as fallback method.
        Scan up to 500 processes (increased from 100).
        Filter out AppData directories.
        """
        try:
            scan_count = 0
            for proc in psutil.process_iter(['pid', 'name', 'exe']):
                scan_count += 1
                
                # Limit scan untuk performance (increased to 500)
                if scan_count > 500:
                    print(f"[WorkspaceDetector] Warning: Process scan limit reached ({scan_count}), stopping early")
                    break
                
                if 'Code.exe' in proc.info.get('name', ''):
                    try:
                        cwd = Path(proc.cwd())
                        cwd_str = str(cwd)
                        
                        # Skip if doesn't exist
                        if not cwd.exists():
                            continue
                        
                        # Skip AppData directories (VS Code installation)
                        if "AppData" in cwd_str:
                            continue
                        
                        print(f"[WorkspaceDetector] Found VS Code workspace: {cwd}")
                        return cwd
                        
                    except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                        continue
                        
        except Exception as e:
            print(f"[WorkspaceDetector] Process detection error: {e}")
        
        return None


class ProjectContext:
    def __init__(self, workspace_path: Path):
        self.workspace = workspace_path
        self.ignored_dirs = {
            'node_modules', '.git', '__pycache__', '.venv', 'venv',
            'dist', 'build', '.next', '.cache', 'coverage', '.pytest_cache'
        }
    
    def get_file_tree(self, max_depth: int = 3, max_lines: int = 500, max_chars: int = 50000) -> str:
        lines = []
        self._build_tree(self.workspace, lines, 0, max_depth)
        
        # Limit output size
        result = '\n'.join(lines)
        
        if len(lines) > max_lines:
            print(f"[ProjectContext] Warning: File tree truncated from {len(lines)} to {max_lines} lines")
            lines = lines[:max_lines]
            result = '\n'.join(lines) + f"\n... ({len(lines) - max_lines} more lines omitted)"
        
        if len(result) > max_chars:
            print(f"[ProjectContext] Warning: File tree truncated from {len(result)} to {max_chars} chars")
            result = result[:max_chars] + f"\n... (truncated, original size: {len(result)} chars)"
        
        return result
    
    def _build_tree(self, path: Path, lines: list, depth: int, max_depth: int, max_items_per_dir: int = 50):
        if depth > max_depth:
            return
        
        indent = "  " * depth
        
        try:
            items = sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
            
            # Limit items per directory untuk performance
            if len(items) > max_items_per_dir:
                print(f"[ProjectContext] Warning: Directory {path} has {len(items)} items, limiting to {max_items_per_dir}")
                items = items[:max_items_per_dir]
                lines.append(f"{indent}... ({len(items) - max_items_per_dir} more items omitted)")
            
            for item in items:
                if item.is_dir() and item.name in self.ignored_dirs:
                    continue
                
                if item.is_dir():
                    lines.append(f"{indent}{item.name}/")
                    self._build_tree(item, lines, depth + 1, max_depth, max_items_per_dir)
                else:
                    lines.append(f"{indent}{item.name}")
        except PermissionError:
            pass
    
    def get_dependencies(self) -> str:
        deps_info = []
        
        package_json = self.workspace / "package.json"
        if package_json.exists():
            try:
                with open(package_json, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    deps = data.get('dependencies', {})
                    dev_deps = data.get('devDependencies', {})
                    
                    deps_info.append("=== package.json ===")
                    if deps:
                        deps_info.append("Dependencies:")
                        for pkg, version in list(deps.items())[:20]:
                            deps_info.append(f"  - {pkg}: {version}")
                    
                    if dev_deps:
                        deps_info.append("DevDependencies:")
                        for pkg, version in list(dev_deps.items())[:20]:
                            deps_info.append(f"  - {pkg}: {version}")
            except Exception as e:
                deps_info.append(f"Error reading package.json: {e}")
        
        requirements_txt = self.workspace / "requirements.txt"
        if requirements_txt.exists():
            try:
                with open(requirements_txt, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    deps_info.append("\n=== requirements.txt ===")
                    for line in lines[:30]:
                        line = line.strip()
                        if line and not line.startswith('#'):
                            deps_info.append(f"  - {line}")
            except Exception as e:
                deps_info.append(f"Error reading requirements.txt: {e}")
        
        cargo_toml = self.workspace / "Cargo.toml"
        if cargo_toml.exists():
            try:
                with open(cargo_toml, 'r', encoding='utf-8') as f:
                    content = f.read()
                    deps_info.append("\n=== Cargo.toml ===")
                    if '[dependencies]' in content:
                        start = content.find('[dependencies]')
                        end = content.find('[', start + 1)
                        if end == -1:
                            end = len(content)
                        deps_section = content[start:end]
                        for line in deps_section.split('\n')[1:20]:
                            line = line.strip()
                            if line and '=' in line:
                                deps_info.append(f"  - {line}")
            except Exception as e:
                deps_info.append(f"Error reading Cargo.toml: {e}")
        
        return '\n'.join(deps_info) if deps_info else "No dependencies file found"
    
    def get_context(self) -> dict:
        return {
            'file_tree': self.get_file_tree(max_depth=3),
            'dependencies': self.get_dependencies(),
            'workspace_path': str(self.workspace)
        }


class FileOperations:
    def __init__(self, workspace_path: Path):
        self.workspace = workspace_path
        self.ignored_dirs = {
            'node_modules', '.git', '__pycache__', '.venv', 'venv',
            'dist', 'build', '.next', '.cache', 'coverage', '.pytest_cache',
            '.idea', '.vscode', 'target', 'bin', 'obj'
        }
    
    def read_file(self, file_path: Path, max_lines: int = None) -> str | None:
        try:
            if not file_path.exists():
                print(f"[FileOperations] File not found: {file_path}")
                return None
            
            # Check file size before reading
            file_size = file_path.stat().st_size
            if file_size > 10 * 1024 * 1024:  # 10 MB limit
                print(f"[FileOperations] Warning: File too large ({file_size} bytes), skipping: {file_path}")
                return None
            
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                if max_lines:
                    lines = []
                    for i, line in enumerate(f):
                        if i >= max_lines:
                            break
                        lines.append(line)
                    return ''.join(lines)
                else:
                    return f.read()
        except PermissionError:
            print(f"[FileOperations] Permission denied: {file_path}")
            return None
        except Exception as e:
            print(f"[FileOperations] Error reading {file_path}: {e}")
            return None
    
    def write_file(self, file_path: Path, content: str, dry_run: bool = True) -> dict:
        try:
            # Validate inputs
            if not content:
                return {'error': 'Empty content provided', 'file_path': str(file_path)}
            
            # Check content size
            if len(content) > 1024 * 1024:  # 1 MB limit
                return {'error': f'Content too large ({len(content)} bytes)', 'file_path': str(file_path)}
            
            # Validate path
            try:
                file_path = Path(file_path).resolve()
                if not file_path.is_absolute():
                    file_path = self.workspace / file_path
            except Exception as e:
                return {'error': f'Invalid file path: {e}', 'file_path': str(file_path)}
            
            original_content = None
            if file_path.exists():
                original_content = self.read_file(file_path)
            
            diff = self._generate_diff(file_path, original_content, content)
            
            result = {
                'file_path': str(file_path),
                'original_content': original_content,
                'new_content': content,
                'diff': diff,
                'is_new_file': original_content is None
            }
            
            if not dry_run:
                # Create parent directories
                try:
                    file_path.parent.mkdir(parents=True, exist_ok=True)
                except Exception as e:
                    return {'error': f'Cannot create directory: {e}', 'file_path': str(file_path)}
                
                # Write file
                try:
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write(content)
                    result['applied'] = True
                except PermissionError:
                    return {'error': 'Permission denied when writing file', 'file_path': str(file_path)}
            else:
                result['applied'] = False
            
            return result
        except Exception as e:
            return {'error': f'Unexpected error: {str(e)}', 'file_path': str(file_path)}
    
    def edit_file(self, file_path: Path, old_string: str, new_string: str, 
                  dry_run: bool = True) -> dict:
        try:
            # Validate inputs
            if not old_string:
                return {'error': 'Empty old_string provided', 'file_path': str(file_path)}
            if not new_string:
                return {'error': 'Empty new_string provided', 'file_path': str(file_path)}
            
            # Validate path
            try:
                file_path = Path(file_path).resolve()
                if not file_path.is_absolute():
                    file_path = self.workspace / file_path
            except Exception as e:
                return {'error': f'Invalid file path: {e}', 'file_path': str(file_path)}
            
            if not file_path.exists():
                return {'error': f'File not found: {file_path}', 'file_path': str(file_path)}
            
            original_content = self.read_file(file_path)
            if original_content is None:
                return {'error': f'Cannot read file: {file_path}', 'file_path': str(file_path)}
            
            if old_string not in original_content:
                # Try to find similar strings for better error message
                return {
                    'error': f'String not found in file',
                    'file_path': str(file_path),
                    'searched_string': old_string[:100],
                    'suggestion': 'Check if the old_string exactly matches the content in the file'
                }
            
            # Count occurrences to warn about multiple matches
            count = original_content.count(old_string)
            if count > 1:
                print(f"[FileOperations] Warning: Found {count} occurrences, only replacing first one")
            
            new_content = original_content.replace(old_string, new_string, 1)
            return self.write_file(file_path, new_content, dry_run=dry_run)
        except Exception as e:
            return {'error': f'Unexpected error: {str(e)}', 'file_path': str(file_path)}
    
    def _generate_diff(self, file_path: Path, original: str | None, new: str) -> str:
        if original is None:
            original_lines = []
        else:
            original_lines = original.splitlines(keepends=True)
        
        new_lines = new.splitlines(keepends=True)
        
        diff = difflib.unified_diff(
            original_lines,
            new_lines,
            fromfile=f"a/{file_path.name}",
            tofile=f"b/{file_path.name}",
            lineterm=''
        )
        
        return ''.join(diff)
    
    def find_relevant_files(self, query: str, max_files: int = 5, max_scan_files: int = 1000) -> list[Path]:
        query_lower = query.lower()
        
        keywords = re.findall(r'\w+', query_lower)
        keywords = [kw for kw in keywords if len(kw) > 3 and kw not in {
            'buat', 'tambah', 'edit', 'fix', 'refactor', 'function', 'class',
            'component', 'module', 'file', 'dengan', 'untuk', 'dari', 'yang'
        }]
        
        relevant_files = []
        scored_files = []
        scanned_count = 0
        
        try:
            for root, dirs, files in os.walk(self.workspace):
                # Filter out ignored directories
                dirs[:] = [d for d in dirs if d not in self.ignored_dirs]
                
                for file in files:
                    scanned_count += 1
                    
                    # Limit scan untuk performance
                    if scanned_count > max_scan_files:
                        print(f"[FileOperations] Warning: Scan limit reached ({max_scan_files} files), stopping early")
                        break
                    
                    file_path = Path(root) / file
                    score = 0
                    
                    file_name_lower = file.lower()
                    for keyword in keywords:
                        if keyword in file_name_lower:
                            score += 2
                    
                    # Check file extension
                    if file_path.suffix.lower() in {'.py', '.js', '.ts', '.tsx', '.jsx', '.vue', '.rs', '.java', '.cpp', '.c', '.h'}:
                        score += 1
                    
                    if score > 0:
                        scored_files.append((score, file_path))
                
                if scanned_count > max_scan_files:
                    break
        
        except Exception as e:
            print(f"[FileOperations] Error scanning files: {e}")
        
        scored_files.sort(key=lambda x: x[0], reverse=True)
        relevant_files = [path for score, path in scored_files[:max_files]]
        
        return relevant_files


class DiffManager:
    def __init__(self, temp_dir: Path = None):
        if temp_dir is None:
            temp_dir = Path(os.getenv('TEMP')) / 'evy_coding_diffs'
        self.temp_dir = temp_dir
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.pending_changes = {}
    
    def store_change(self, change_id: str, file_path: str, original_content: str | None,
                     new_content: str, diff: str) -> None:
        change_data = {
            'file_path': file_path,
            'original_content': original_content,
            'new_content': new_content,
            'diff': diff,
            'timestamp': datetime.now().isoformat()
        }
        
        self.pending_changes[change_id] = change_data
        
        change_file = self.temp_dir / f"{change_id}.json"
        with open(change_file, 'w', encoding='utf-8') as f:
            json.dump(change_data, f, indent=2, ensure_ascii=False)
    
    def apply_change(self, change_id: str) -> dict:
        try:
            if change_id not in self.pending_changes:
                return {'error': f'Change not found: {change_id}'}
            
            change = self.pending_changes[change_id]
            file_path = Path(change['file_path'])
            
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(change['new_content'])
            
            self._cleanup_change(change_id)
            
            return {'success': True, 'file_path': str(file_path)}
        except Exception as e:
            return {'error': str(e)}
    
    def discard_change(self, change_id: str) -> dict:
        try:
            self._cleanup_change(change_id)
            return {'success': True}
        except Exception as e:
            return {'error': str(e)}
    
    def _cleanup_change(self, change_id: str):
        if change_id in self.pending_changes:
            del self.pending_changes[change_id]
        
        change_file = self.temp_dir / f"{change_id}.json"
        if change_file.exists():
            change_file.unlink()
    
    def get_pending_changes(self) -> dict:
        return self.pending_changes.copy()
    
    def generate_diff_summary(self, diff: str) -> str:
        lines = diff.split('\n')
        added = sum(1 for line in lines if line.startswith('+') and not line.startswith('+++'))
        removed = sum(1 for line in lines if line.startswith('-') and not line.startswith('---'))
        
        summary = []
        if added > 0:
            summary.append(f"{added} baris ditambahkan")
        if removed > 0:
            summary.append(f"{removed} baris dihapus")
        
        return ', '.join(summary) if summary else "tidak ada perubahan"


class TerminalRunner:
    def __init__(self, workspace_path: Path):
        self.workspace = workspace_path
    
    def run_command(self, command: str, timeout: int = None) -> dict:
        if timeout is None:
            timeout = self._detect_timeout(command)
        
        # Validate command
        if not command or not command.strip():
            return {
                'success': False,
                'error': 'Empty command provided',
                'command': command
            }
        
        # Security check - prevent dangerous commands
        dangerous_patterns = ['rm -rf /', 'format c:', 'del /s /q c:\\']
        command_lower = command.lower()
        if any(pattern in command_lower for pattern in dangerous_patterns):
            return {
                'success': False,
                'error': 'Command blocked for security reasons',
                'command': command
            }
        
        try:
            # Validate workspace exists
            if not self.workspace.exists():
                return {
                    'success': False,
                    'error': f'Workspace does not exist: {self.workspace}',
                    'command': command
                }
            
            result = subprocess.run(
                command,
                shell=True,
                cwd=self.workspace,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            # Truncate large outputs
            stdout = result.stdout[:10000] if result.stdout else ""
            stderr = result.stderr[:5000] if result.stderr else ""
            
            return {
                'success': result.returncode == 0,
                'returncode': result.returncode,
                'stdout': stdout,
                'stderr': stderr,
                'command': command
            }
        except subprocess.TimeoutExpired:
            return {
                'success': False,
                'error': f'Command timeout after {timeout} seconds',
                'command': command,
                'suggestion': 'Try increasing timeout or check if command is hanging'
            }
        except Exception as e:
            return {
                'success': False,
                'error': f'Unexpected error: {str(e)}',
                'command': command
            }
    
    def _detect_timeout(self, command: str) -> int:
        command_lower = command.lower()
        
        if 'npm install' in command_lower or 'yarn install' in command_lower:
            return 300
        elif 'npm run build' in command_lower or 'yarn build' in command_lower:
            return 120
        else:
            return 30
    
    def run_async(self, command: str, callback=None):
        def run_in_thread():
            result = self.run_command(command)
            if callback:
                callback(result)
        
        thread = threading.Thread(target=run_in_thread, daemon=True)
        thread.start()
        return thread


class GitOperations:
    def __init__(self, workspace_path: Path):
        self.workspace = workspace_path
        self.terminal = TerminalRunner(workspace_path)
    
    def is_git_repo(self) -> bool:
        result = self.terminal.run_command('git rev-parse --is-inside-work-tree')
        return result.get('success', False) and 'true' in result.get('stdout', '').lower()
    
    def status(self) -> dict:
        if not self.is_git_repo():
            return {'error': 'Not a git repository', 'workspace': str(self.workspace)}
        return self.terminal.run_command('git status --short')
    
    def add(self, files: list[str] = None) -> dict:
        if not self.is_git_repo():
            return {'error': 'Not a git repository', 'workspace': str(self.workspace)}
        if files:
            file_str = ' '.join(f'"{f}"' for f in files)
            return self.terminal.run_command(f'git add {file_str}')
        else:
            return self.terminal.run_command('git add .')
    
    def commit(self, message: str) -> dict:
        if not self.is_git_repo():
            return {'error': 'Not a git repository', 'workspace': str(self.workspace)}
        if not message or not message.strip():
            return {'error': 'Empty commit message'}
        # Escape quotes in message
        safe_message = message.replace('"', '\\"')
        return self.terminal.run_command(f'git commit -m "{safe_message}"')
    
    def push(self) -> dict:
        if not self.is_git_repo():
            return {'error': 'Not a git repository', 'workspace': str(self.workspace)}
        return self.terminal.run_command('git push')
    
    def pull(self) -> dict:
        if not self.is_git_repo():
            return {'error': 'Not a git repository', 'workspace': str(self.workspace)}
        return self.terminal.run_command('git pull')
    
    def diff(self) -> dict:
        if not self.is_git_repo():
            return {'error': 'Not a git repository', 'workspace': str(self.workspace)}
        return self.terminal.run_command('git diff')
    
    def log(self, n: int = 10) -> dict:
        if not self.is_git_repo():
            return {'error': 'Not a git repository', 'workspace': str(self.workspace)}
        return self.terminal.run_command(f'git log --oneline -{n}')


class CodeGenerator:
    def __init__(self, api_key: str, model: str = "qwen-3.7-max", max_retries: int = 2):
        from openai import OpenAI
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://api.openai.com/v1"
        )
        self.model = model
        self.max_retries = max_retries
        self.max_context_chars = 12000  # Limit context size to avoid token overflow
        self.max_request_chars = 15000  # Total request size limit
    
    def generate_code(self, context: dict, user_request: str, 
                     plan_context: dict = None) -> dict:
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(context, user_request, plan_context)
        
        # Validate request size
        total_chars = len(system_prompt) + len(user_prompt)
        if total_chars > self.max_request_chars:
            print(f"[CodeGenerator] Warning: Request size ({total_chars} chars) exceeds limit, truncating context")
            user_prompt = user_prompt[:self.max_request_chars - len(system_prompt) - 500]
        
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                if attempt > 0:
                    print(f"[CodeGenerator] Retry attempt {attempt}/{self.max_retries}")
                
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=0.3,
                    max_tokens=4000,
                    timeout=60
                )
                
                content = response.choices[0].message.content
                
                if not content or not content.strip():
                    raise ValueError("Empty response from LLM")
                
                actions = self._parse_actions(content)
                
                return {
                    'success': True,
                    'response': content,
                    'actions': actions,
                    'attempts': attempt + 1
                }
            
            except Exception as e:
                last_error = e
                error_msg = str(e)
                print(f"[CodeGenerator] Attempt {attempt + 1} failed: {error_msg}")
                
                # Don't retry on certain errors
                if 'rate_limit' in error_msg.lower() or 'quota' in error_msg.lower():
                    break
                if 'invalid_api_key' in error_msg.lower():
                    break
                
                if attempt < self.max_retries:
                    import time
                    time.sleep(2 ** attempt)  # Exponential backoff
        
        return {
            'success': False,
            'error': f"Failed after {self.max_retries + 1} attempts: {str(last_error)}",
            'attempts': self.max_retries + 1
        }
    
    def _build_system_prompt(self) -> str:
        return """Kamu adalah Evy, voice-powered coding assistant yang membantu developer menulis kode.

TUGAS KAMU:
1. Analisis request user dengan teliti
2. Gunakan project context yang diberikan (file tree, dependencies, relevant files)
3. Generate code yang clean, production-ready, dan mengikuti existing patterns
4. Jelaskan perubahan yang akan dilakukan SEBELUM apply
5. Minta konfirmasi jika perubahan besar

FORMAT OUTPUT:
Gunakan format terstruktur berikut:

```
PENJELASAN:
[Jelaskan apa yang akan kamu lakukan dalam 2-3 kalimat]

FILE: path/to/file.py
ACTION: write | edit
CONTENT:
```python
[code di sini]
```

[atau untuk edit]
OLD:
```python
[code lama]
```

NEW:
```python
[code baru]
```

FILE: path/to/another/file.js
ACTION: write | edit
...
```

ATURAN:
- Untuk file baru: ACTION: write dengan CONTENT lengkap
- Untuk edit file: ACTION: edit dengan OLD dan NEW
- Boleh multiple FILE blocks dalam satu response
- JANGAN apply perubahan, hanya generate dan jelaskan
- Gunakan bahasa Indonesia untuk penjelasan
- Code harus dalam bahasa yang sesuai project (Python/JavaScript/Rust/dll)
"""
    
    def _build_user_prompt(self, context: dict, user_request: str,
                          plan_context: dict = None) -> str:
        prompt = f"""PROJECT CONTEXT:

File Tree:
{context.get('file_tree', 'N/A')}

Dependencies:
{context.get('dependencies', 'N/A')}

Workspace: {context.get('workspace_path', 'N/A')}
"""
        
        if context.get('relevant_files'):
            prompt += "\nRelevant Files:\n"
            for file_info in context['relevant_files']:
                prompt += f"\n--- {file_info['path']} ---\n"
                prompt += file_info['content'][:2000] + "\n"
        
        if plan_context:
            prompt += f"\n\nPLAN CONTEXT:\n{plan_context.get('plan_summary', '')}\n"
            if plan_context.get('conversation_history'):
                prompt += "\nConversation History:\n"
                for msg in plan_context['conversation_history'][-6:]:
                    prompt += f"- {msg.get('role')}: {msg.get('content')[:200]}\n"
        
        prompt += f"\n\nUSER REQUEST:\n{user_request}\n"
        
        prompt += "\nBerikan response dengan format yang sudah ditentukan. Jelaskan perubahan yang akan dilakukan, lalu berikan code untuk setiap file yang perlu diubah."
        
        return prompt
    
    def _parse_actions(self, content: str) -> list[dict]:
        actions = []
        
        file_blocks = re.split(r'(?=^FILE:)', content, flags=re.MULTILINE)
        
        for block in file_blocks:
            if not block.strip().startswith('FILE:'):
                continue
            
            file_match = re.search(r'FILE:\s*(.+?)$', block, re.MULTILINE)
            action_match = re.search(r'ACTION:\s*(write|edit)', block, re.IGNORECASE)
            
            if not file_match or not action_match:
                continue
            
            file_path = file_match.group(1).strip()
            action_type = action_match.group(1).lower()
            
            if action_type == 'write':
                content_match = re.search(r'CONTENT:\s*```[\w]*\n(.*?)```', 
                                        block, re.DOTALL)
                if content_match:
                    actions.append({
                        'type': 'write',
                        'file_path': file_path,
                        'content': content_match.group(1).strip()
                    })
            
            elif action_type == 'edit':
                old_match = re.search(r'OLD:\s*```[\w]*\n(.*?)```', 
                                    block, re.DOTALL)
                new_match = re.search(r'NEW:\s*```[\w]*\n(.*?)```', 
                                    block, re.DOTALL)
                
                if old_match and new_match:
                    actions.append({
                        'type': 'edit',
                        'file_path': file_path,
                        'old_string': old_match.group(1).strip(),
                        'new_string': new_match.group(1).strip()
                    })
        
        return actions


class PlanMode:
    def __init__(self, workspace_path: Path, api_key: str, model: str = "qwen-3.7-max", max_retries: int = 2):
        self.workspace_path = workspace_path
        self.api_key = api_key
        self.model = model
        self.max_retries = max_retries
        self.conversation_history = []
        self.plan_summary = None
        self.is_active = True
        
        from openai import OpenAI
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://api.openai.com/v1"
        )
    
    def start_planning(self, user_request: str, context: dict) -> str:
        """Start planning session dengan user request"""
        self.is_active = True
        self.conversation_history = []
        self.plan_summary = None
        
        system_prompt = self._build_planning_system_prompt()
        user_prompt = self._build_planning_user_prompt(context, user_request)
        
        self.conversation_history.append({"role": "user", "content": user_request})
        
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                if attempt > 0:
                    print(f"[PlanMode] Retry attempt {attempt}/{self.max_retries}")
                
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=0.7,
                    max_tokens=2000,
                    timeout=60
                )
                
                assistant_message = response.choices[0].message.content
                
                if not assistant_message or not assistant_message.strip():
                    raise ValueError("Empty response from LLM")
                
                self.conversation_history.append({"role": "assistant", "content": assistant_message})
                
                return assistant_message
            
            except Exception as e:
                last_error = e
                error_msg = str(e)
                print(f"[PlanMode] Attempt {attempt + 1} failed: {error_msg}")
                
                # Don't retry on certain errors
                if 'rate_limit' in error_msg.lower() or 'quota' in error_msg.lower():
                    break
                if 'invalid_api_key' in error_msg.lower():
                    break
                
                if attempt < self.max_retries:
                    import time
                    time.sleep(2 ** attempt)
        
        error_msg = f"Error starting plan mode after {self.max_retries + 1} attempts: {str(last_error)}"
        print(f"[PlanMode] {error_msg}")
        return error_msg
    
    def continue_planning(self, user_message: str) -> str:
        """Continue planning conversation"""
        if not self.is_active:
            return "Plan mode tidak aktif. Gunakan 'mode plan' untuk memulai."
        
        self.conversation_history.append({"role": "user", "content": user_message})
        
        messages = [
            {"role": "system", "content": self._build_planning_system_prompt()}
        ]
        messages.extend(self.conversation_history)
        
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                if attempt > 0:
                    print(f"[PlanMode] Retry attempt {attempt}/{self.max_retries}")
                
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0.7,
                    max_tokens=2000,
                    timeout=60
                )
                
                assistant_message = response.choices[0].message.content
                
                if not assistant_message or not assistant_message.strip():
                    raise ValueError("Empty response from LLM")
                
                self.conversation_history.append({"role": "assistant", "content": assistant_message})
                
                return assistant_message
            
            except Exception as e:
                last_error = e
                error_msg = str(e)
                print(f"[PlanMode] Attempt {attempt + 1} failed: {error_msg}")
                
                # Don't retry on certain errors
                if 'rate_limit' in error_msg.lower() or 'quota' in error_msg.lower():
                    break
                if 'invalid_api_key' in error_msg.lower():
                    break
                
                if attempt < self.max_retries:
                    import time
                    time.sleep(2 ** attempt)
        
        error_msg = f"Error continuing plan after {self.max_retries + 1} attempts: {str(last_error)}"
        print(f"[PlanMode] {error_msg}")
        return error_msg
    
    def finalize_plan(self) -> dict:
        """Finalize planning session dan prepare untuk eksekusi"""
        if not self.is_active:
            return {"error": "Plan mode tidak aktif"}
        
        # Generate plan summary
        summary_prompt = """Berdasarkan diskusi planning kita, buat summary singkat yang mencakup:
1. Tujuan utama task ini
2. File-file yang akan dibuat/diedit
3. Approach/strategy yang akan digunakan
4. Langkah-langkah implementasi

Format dalam paragraf singkat (3-5 kalimat)."""
        
        messages = [
            {"role": "system", "content": summary_prompt}
        ]
        messages.extend(self.conversation_history)
        
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                if attempt > 0:
                    print(f"[PlanMode] Retry attempt {attempt}/{self.max_retries}")
                
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0.3,
                    max_tokens=1000,
                    timeout=60
                )
                
                self.plan_summary = response.choices[0].message.content
                
                if not self.plan_summary or not self.plan_summary.strip():
                    raise ValueError("Empty plan summary from LLM")
                
                # Prepare plan context untuk CodeGenerator
                plan_context = {
                    "plan_summary": self.plan_summary,
                    "conversation_history": self.conversation_history.copy()
                }
                
                # Reset plan mode
                self.is_active = False
                
                return {
                    "success": True,
                    "plan_summary": self.plan_summary,
                    "plan_context": plan_context
                }
            
            except Exception as e:
                last_error = e
                error_msg = str(e)
                print(f"[PlanMode] Finalize attempt {attempt + 1} failed: {error_msg}")
                
                # Don't retry on certain errors
                if 'rate_limit' in error_msg.lower() or 'quota' in error_msg.lower():
                    break
                if 'invalid_api_key' in error_msg.lower():
                    break
                
                if attempt < self.max_retries:
                    import time
                    time.sleep(2 ** attempt)
        
        return {"error": f"Error finalizing plan after {self.max_retries + 1} attempts: {str(last_error)}"}
    
    def get_conversation_summary(self) -> str:
        """Get summary of planning conversation"""
        if not self.conversation_history:
            return "Belum ada conversation."
        
        summary = f"Total messages: {len(self.conversation_history)}\n"
        for i, msg in enumerate(self.conversation_history[-6:], 1):  # Last 6 messages
            role = msg["role"].upper()
            content = msg["content"][:100] + "..." if len(msg["content"]) > 100 else msg["content"]
            summary += f"{i}. [{role}]: {content}\n"
        
        return summary
    
    def _build_planning_system_prompt(self) -> str:
        return """Kamu adalah Evy dalam MODE PLAN. Tugas kamu adalah membantu user merencanakan implementasi fitur atau perubahan kode SEBELUM eksekusi.

ATURAN MODE PLAN:
1. JANGAN langsung generate code yang siap pakai
2. Fokus pada DISKUSI dan PLANNING
3. Tanya pertanyaan untuk klarifikasi requirement
4. Jelaskan approach yang akan digunakan
5. Diskusikan trade-offs dan alternatif
6. Bantu user memahami implikasi perubahan

GAYA KOMUNIKASI:
- Gunakan bahasa Indonesia yang santai dan friendly
- Jelaskan konsep teknis dengan sederhana
- Berikan contoh kecil/pseudocode jika perlu (bukan full implementation)
- Tanya satu pertanyaan per turn untuk tidak overwhelming

FORMAT RESPONSE:
- Gunakan markdown untuk formatting
- Code snippets kecil boleh (untuk ilustrasi)
- List untuk menjelaskan steps/approach
- Bold untuk important points

Tujuan: User harus punya pemahaman yang jelas tentang apa yang akan dilakukan SEBELUM kamu mulai coding."""
    
    def _build_planning_user_prompt(self, context: dict, user_request: str) -> str:
        prompt = f"""PROJECT CONTEXT:

File Tree:
{context.get('file_tree', 'N/A')}

Dependencies:
{context.get('dependencies', 'N/A')}

Workspace: {context.get('workspace_path', 'N/A')}
"""
        
        if context.get('relevant_files'):
            prompt += "\nRelevant Files:\n"
            for file_info in context['relevant_files'][:3]:  # Max 3 files untuk planning
                prompt += f"\n--- {file_info['path']} ---\n"
                prompt += file_info['content'][:500] + "...\n"  # Shorter preview untuk planning
        
        prompt += f"\n\nUSER REQUEST:\n{user_request}\n"
        prompt += "\nBantu saya merencanakan implementasi ini. Apa yang perlu saya pertimbangkan?"
        
        return prompt
