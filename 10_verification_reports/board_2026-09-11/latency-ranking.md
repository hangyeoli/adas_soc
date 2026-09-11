# Camera 100-frame latency ranking

Measured frames: 100; FPGA mean: 1343.488 ms.

| Rank | Operation | Mean ms | P50 ms | P95 ms | P99 ms | Share |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 00_conv | 381.479 | 381.470 | 381.560 | 381.982 | 28.39% |
| 2 | 12_conv | 246.252 | 246.080 | 246.475 | 252.033 | 18.33% |
| 3 | 02_conv | 146.115 | 146.095 | 146.197 | 146.632 | 10.88% |
| 4 | 21_conv | 99.647 | 99.632 | 99.819 | 99.934 | 7.42% |
| 5 | 01_maxpool | 90.760 | 90.624 | 91.159 | 92.960 | 6.76% |
| 6 | 04_conv | 78.703 | 78.697 | 78.797 | 78.987 | 5.86% |
| 7 | 10_conv | 63.016 | 62.964 | 63.312 | 63.399 | 4.69% |
| 8 | 14_conv | 63.001 | 62.971 | 63.169 | 63.526 | 4.69% |
| 9 | 06_conv | 46.515 | 46.513 | 46.608 | 46.683 | 3.46% |
| 10 | 13_conv | 38.483 | 38.463 | 38.606 | 38.686 | 2.86% |
| 11 | 08_conv | 36.858 | 36.859 | 36.948 | 37.135 | 2.74% |
| 12 | 03_maxpool | 25.428 | 25.412 | 25.578 | 25.674 | 1.89% |
| 13 | 05_maxpool | 7.479 | 7.486 | 7.527 | 7.537 | 0.56% |
| 14 | 18_conv | 5.404 | 5.399 | 5.472 | 5.493 | 0.40% |
| 15 | 22_conv | 4.202 | 4.185 | 4.293 | 4.308 | 0.31% |
| 16 | 07_maxpool | 2.453 | 2.441 | 2.528 | 2.598 | 0.18% |
| 17 | 15_conv | 2.447 | 2.441 | 2.482 | 2.526 | 0.18% |
| 18 | 20_route | 1.754 | 1.744 | 1.843 | 1.860 | 0.13% |
| 19 | 11_maxpool | 1.571 | 1.570 | 1.610 | 1.619 | 0.12% |
| 20 | 09_maxpool | 1.036 | 1.048 | 1.062 | 1.155 | 0.08% |
| 21 | 19_upsample | 0.527 | 0.526 | 0.530 | 0.563 | 0.04% |
| 22 | 17_route | 0.358 | 0.353 | 0.367 | 0.459 | 0.03% |

Top 3 share: 57.60%.
Top 5 share: 71.77%.

| Stage | Mean | P50 | P95 | P99 |
| --- | --- | --- | --- | --- |
| capture_fps | 3.792 | 3.746 | 4.167 | 4.167 |
| preprocess_ms | 7.347 | 7.213 | 7.620 | 8.221 |
| dma_input_ms | 0.357 | 0.359 | 0.488 | 0.588 |
| fpga_total_ms | 1343.488 | 1343.137 | 1343.867 | 1351.903 |
| runtime_ms | 1346.240 | 1345.878 | 1346.669 | 1355.146 |
| decode_nms_ms | 5.452 | 5.403 | 5.605 | 6.145 |
| jpeg_publish_ms | 6.785 | 5.899 | 11.546 | 12.845 |
| processing_ms | 1368.725 | 1367.517 | 1373.097 | 1377.148 |
| frame_available_to_publish_ms | 1503.673 | 1509.719 | 1622.156 | 1630.087 |
| output_interval_ms | 1374.310 | 1369.604 | 1375.230 | 1382.671 |
| dropped_frames | 209.850 | 210.000 | 399.200 | 416.040 |
| detections | 0.000 | 0.000 | 0.000 | 0.000 |
| cpu_percent | 4.237 | 3.598 | 5.212 | 24.243 |
| temperature_c | 28.242 | 28.288 | 29.256 | 29.766 |
| cma_used_kb | 334972.000 | 334972.000 | 334972.000 | 334972.000 |
| cma_free_kb | 484228.000 | 484228.000 | 484228.000 | 484228.000 |

processing_ms excludes camera exposure and browser/network rendering
output_interval_ms includes waits; first interval includes camera startup
frame_available_to_publish_ms starts after OpenCV read; excludes sensor exposure and browser rendering
FPGA times include polling and DDR stalls; CPU is whole-system utilization
