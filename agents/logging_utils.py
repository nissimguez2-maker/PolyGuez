@@ def get_logger(name: Optional[str] = None) -> logging.Logger:
-  logger = logging.getLogger(logger_name)
+  logger = logging.getLogger(logger_name)
+
@@ def get_logger(name: Optional[str] = None) -> logging.Logger:
-  if logger.handlers:
-    return logger
-
-  logger.setLevel(logging.INFO)
+  if logger.handlers:
+    return logger
+
+  logger.setLevel(logging.INFO)
@@ def get_logger(name: Optional[str] = None) -> logging.Logger:
-  handler = logging.StreamHandler()
-  formatter = logging.Formatter(
-      fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
-      datefmt="%Y-%m-%d %H:%M:%S",
-  )
-  handler.setFormatter(formatter)
-  logger.addHandler(handler)
+  stream_handler = logging.StreamHandler()
+  formatter = logging.Formatter(
+      fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
+      datefmt="%Y-%m-%d %H:%M:%S",
+  )
+  stream_handler.setFormatter(formatter)
+  logger.addHandler(stream_handler)
+
+  # Optionally add a file handler when LOG_FILE environment variable is set.
+  log_file = os.environ.get("POLYMARKET_LOG_FILE")
+  if log_file:
+    file_handler = logging.FileHandler(log_file)
+    file_handler.setFormatter(formatter)
+    logger.addHandler(file_handler)
@@
   return logger
