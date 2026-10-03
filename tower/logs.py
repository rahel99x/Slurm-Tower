"""An incremental log buffer: the file is read once (its last ``max_bytes`` when larger), then only the bytes
appended since, so following costs one stat per frame; a shrunken or replaced file reloads.  Windows are taken by
absolute line index and always bounded, so a page is a page whatever the scroll position."""
from __future__ import annotations

import codecs
import re
import time
from typing import List, Optional, Tuple

from .remote import LocalFiles


class LogBuffer:
    def __init__(self, path: str, max_bytes: int = 32 << 20, files: Optional[LocalFiles] = None):
        self.path = path
        self.max_bytes = max(1, int(max_bytes))
        self.files = files or LocalFiles()
        self.last_refresh = 0.0
        self.lines: List[str] = []
        self.size = 0                        # bytes of the file consumed so far
        self.ident: Optional[Tuple[int, int]] = None   # (device, inode) of the file read
        self.partial = ""                    # an unterminated last line kept until it is completed
        self.truncated = False               # the beginning of the file was skipped (larger than max_bytes)
        self.skipped_bytes = 0
        self.error = ""
        self.reloads = 0
        self._partial_raw = b""
        self._line_bytes: List[int] = []
        self._retained_bytes = 0

    # ---- reading ----------------------------------------------------------------------------------
    def _reset(self):
        self.lines, self.size, self.partial, self.truncated, self.skipped_bytes = [], 0, "", False, 0
        self._partial_raw, self._line_bytes, self._retained_bytes = b"", [], 0

    def refresh(self) -> bool:
        """Bring the buffer up to date; True when anything changed.  A remote file is not re-checked more often
        than ``files.min_refresh`` seconds."""
        if self.files.min_refresh and time.time() - self.last_refresh < self.files.min_refresh:
            return False
        self.last_refresh = time.time()
        try:
            size, ident = self.files.stat(self.path)
        except OSError as e:
            self.error = str(e)
            return False
        self.error = ""
        if self.ident != ident or size < self.size:          # a new file under the same name, or truncation
            self.reloads += 1 if self.ident is not None else 0
            self._reset()
            self.ident = ident
        if size == self.size:
            return False
        offset = max(self.size, size - self.max_bytes)
        jumped = offset > self.size
        # Read one preceding byte to tell a line boundary from a partial first line.
        read_offset = offset - 1 if jumped else offset
        try:
            data = self.files.read(self.path, read_offset, size - read_offset)
        except OSError as e:
            self.error = str(e)
            return False
        consumed = len(data)
        if jumped:
            self.lines, self._line_bytes, self._partial_raw = [], [], b""
            self._retained_bytes = 0
            self.skipped_bytes = offset
            self.truncated = True
            if data.startswith(b"\n"):
                data = data[1:]
            else:
                data = data[1:]
                nl = data.find(b"\n")
                if nl >= 0:
                    self.skipped_bytes += nl + 1
                    data = data[nl + 1:]
        # A file may shrink after stat; only advance by the bytes actually read.
        self.size = read_offset + consumed
        self._retained_bytes += len(data)
        raw = self._partial_raw + data
        # A newline-only burst must not allocate millions of temporary line objects.
        parts = raw.rsplit(b"\n", 200_001)
        if len(parts) > 200_001:
            skipped = len(parts.pop(0)) + 1
            self._retained_bytes -= skipped
            self.skipped_bytes += skipped
            self.truncated = True
        self._partial_raw = parts.pop()
        self.lines.extend(line.decode("utf-8", "replace").replace("\t", "    ").rstrip("\r") for line in parts)
        self._line_bytes.extend(len(line) + 1 for line in parts)
        drop = 0
        while drop < len(self.lines) and (self._retained_bytes > self.max_bytes or len(self.lines) - drop > 200_000):
            self._retained_bytes -= self._line_bytes[drop]
            self.skipped_bytes += self._line_bytes[drop]
            drop += 1
        if drop:
            del self.lines[:drop]
            del self._line_bytes[:drop]
            self.truncated = True
        if len(self._partial_raw) > self.max_bytes:
            skipped = len(self._partial_raw) - self.max_bytes
            self._partial_raw = self._partial_raw[-self.max_bytes:]
            self._retained_bytes -= skipped
            self.skipped_bytes += skipped
            self.truncated = True
        # Keep an incomplete UTF-8 character for the next append instead of corrupting it.
        self.partial = codecs.getincrementaldecoder("utf-8")("replace").decode(self._partial_raw, final=False)
        return True

    # ---- windows ----------------------------------------------------------------------------------
    @property
    def total(self) -> int:
        return len(self.lines) + (1 if self.partial else 0)

    def all_lines(self) -> List[str]:
        return self.lines + ([self.partial] if self.partial else [])

    def clamp_top(self, top: Optional[int], n: int) -> Optional[int]:
        """``top`` as an absolute line index for a page of ``n`` lines; None means following (the last page)."""
        total = self.total
        if top is None or total <= n:
            return None
        return max(0, min(top, total - n))

    def window(self, top: Optional[int], n: int) -> Tuple[List[str], int]:
        """(lines, first index) of the page: the last ``n`` lines when ``top`` is None."""
        total = self.total
        n = max(1, n)
        if top is None or total <= n:
            start = max(0, total - n)
        else:
            start = max(0, min(top, total - n))
        page = self.lines[start:start + n]
        if self.partial and start + n > len(self.lines):
            page.append(self.partial)
        return page, start

    def find(self, pattern: str, from_index: Optional[int] = None, backwards: bool = False) -> Optional[int]:
        """Index of the next line matching ``pattern`` (a regular expression, case-insensitive; a plain string
        when it is not a valid one) before or after ``from_index``; None when nothing matches."""
        try:
            rx = re.compile(pattern, re.IGNORECASE)
        except re.error:
            rx = re.compile(re.escape(pattern), re.IGNORECASE)
        lines = self.all_lines()
        if backwards:
            rng = range((len(lines) - 1) if from_index is None else from_index - 1, -1, -1)
        else:
            rng = range(0 if from_index is None else from_index + 1, len(lines))
        for i in rng:
            if rx.search(lines[i]):
                return i
        return None

    def count(self, pattern: str) -> int:
        try:
            rx = re.compile(pattern, re.IGNORECASE)
        except re.error:
            rx = re.compile(re.escape(pattern), re.IGNORECASE)
        return sum(1 for l in self.all_lines() if rx.search(l))


class LogSession:
    """The log tab's state across frames: one buffer per path, the page position, the search."""

    def __init__(self, max_bytes: int = 32 << 20, files: Optional[LocalFiles] = None):
        self.max_bytes = max_bytes
        self.files = files or LocalFiles()
        self.buffers: dict = {}
        self.path: str = ""
        self.top: Optional[int] = None        # None: following the end
        self.page = 20                        # lines on the last rendered page
        self.search = ""
        self.match: Optional[int] = None
        self.wrap = False                     # long lines wrapped to the width instead of cut
        self.which = "out"                    # out | err: the job's stdout or stderr
        self.file_index = 0                   # 0: stdout / stderr; 1..: the other files of the job's log directory
        self.candidates: dict = {}            # job id -> (time, [paths]) of the other files
        self.bookmarks: dict = {}             # path -> sorted line indices
        self.last_bookmark: Optional[int] = None   # the bookmark the last jump landed on (the next jump continues from it)

    # ---- bookmarks ------------------------------------------------------------------------------
    def toggle_bookmark(self, path: str, index: int) -> bool:
        marks = self.bookmarks.setdefault(path, [])
        if index in marks:
            marks.remove(index)
            if not marks:
                del self.bookmarks[path]
            return False
        marks.append(index)
        marks.sort()
        return True

    def next_bookmark(self, path: str, after: Optional[int]) -> Optional[int]:
        marks = self.bookmarks.get(path, [])
        if not marks:
            return None
        for i in marks:
            if after is None or i > after:
                return i
        return marks[0]                                    # wrap around

    def current_line(self, buf: Optional[LogBuffer]) -> Optional[int]:
        """The line a bookmark or a jump refers to: the match when it is on the page, else the top line when paused,
        the last line when following."""
        if buf is None or buf.total == 0:
            return None
        lines, start = buf.window(self.top, self.page)
        if self.match is not None and start <= self.match < start + len(lines):
            return self.match
        if self.last_bookmark is not None and start <= self.last_bookmark < start + len(lines):
            return self.last_bookmark
        return start if self.top is not None else start + len(lines) - 1

    def buffer(self, path: str) -> Optional[LogBuffer]:
        if not path:
            return None
        if path != self.path:
            self.path, self.top, self.match, self.last_bookmark = path, None, None, None
        buf = self.buffers.get(path)
        if buf is None:
            buf = self.buffers[path] = LogBuffer(path, self.max_bytes, self.files)
            if len(self.buffers) > 8:                      # keep a few; drop the oldest
                oldest = next(iter(self.buffers))
                if oldest != path:
                    del self.buffers[oldest]
        buf.refresh()
        return buf

    @property
    def following(self) -> bool:
        return self.top is None

    def scroll(self, delta: int, buf: Optional[LogBuffer]):
        """Move the page by ``delta`` lines (negative: up); reaching the end resumes following."""
        if buf is None:
            return
        total, n = buf.total, self.page
        cur = self.top if self.top is not None else max(0, total - n)
        new = cur + delta
        if new >= total - n:
            self.top = None
        else:
            self.top = max(0, new)

    def goto(self, index: Optional[int], buf: Optional[LogBuffer]):
        if buf is None:
            return
        if index is None:
            self.top = None
            return
        self.top = buf.clamp_top(max(0, index - self.page // 2), self.page)

    def find_next(self, buf: Optional[LogBuffer], backwards: bool = False) -> Optional[int]:
        if buf is None or not self.search:
            return None
        start = self.match
        if start is None and self.top is not None:
            start = self.top + self.page
        i = buf.find(self.search, start, backwards=backwards)
        if i is None and start is not None:                # wrap around
            i = buf.find(self.search, None, backwards=backwards)
        if i is not None:
            self.match = i
            self.goto(i, buf)
        return i
