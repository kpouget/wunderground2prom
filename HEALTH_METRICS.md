# Weather Station Health Monitoring Metrics

This document describes the health monitoring metrics exposed by the wunderground weather station exporter.

## Overview

The weather station service exposes health metrics to monitor service reliability, API performance, and data freshness. These metrics help detect issues before they cause service outages.

## Health Metrics

### `last_fetch_time{station_id="..."}`
- **Type**: Gauge (Unix timestamp)
- **Description**: Timestamp of the last successful data fetch from each weather station
- **Updated**: Only when API request succeeds and returns valid data
- **Use Case**: Detect stale data or communication issues

**Example Value**: `1704151200` (2024-01-01 20:00:00 UTC)

### `last_fetch_duration{station_id="..."}`
- **Type**: Gauge (seconds)
- **Description**: Duration of the last successful API request
- **Updated**: Only for successful requests (excludes timeouts/errors)
- **Use Case**: Monitor API performance and detect slowdowns

**Example Value**: `2.34` (2.34 seconds)

### `successful_requests_total{station_id="..."}`
- **Type**: Gauge (counter)
- **Description**: Total successful API requests since service startup
- **Updated**: Incremented on each successful data retrieval
- **Use Case**: Calculate success rates and request frequency

**Example Value**: `1440` (24 hours × 60 minutes = 1440 successful requests)

### `temperature_last_change{station_id="..."}`
- **Type**: Gauge (Unix timestamp)
- **Description**: Timestamp when temperature value last changed
- **Updated**: When temperature reading differs from previous value
- **Use Case**: Detect stuck sensors or data validation issues

**Example Value**: `1704151080` (2024-01-01 19:58:00 UTC)

## Accessing Metrics

### View All Health Metrics
```bash
curl http://127.0.0.1:12100/metrics | grep -E "(last_fetch|successful_requests|temperature_last_change)"
```

### View Specific Station
```bash
curl http://127.0.0.1:12100/metrics | grep 'station_id="ICAHOR23"'
```

## Monitoring Examples

### Calculate Data Freshness
```bash
# Time since last successful fetch (seconds)
echo "scale=0; $(date +%s) - $(curl -s http://127.0.0.1:12100/metrics | grep 'last_fetch_time{station_id="ICAHOR23"}' | cut -d' ' -f2)" | bc
```

### Calculate Success Rate
```bash
# Successful requests in last hour (assuming 60-second intervals)
echo "Success rate: $(curl -s http://127.0.0.1:12100/metrics | grep 'successful_requests_total{station_id="ICAHOR23"}' | cut -d' ' -f2)/60"
```

## Prometheus Alerting

### Data Freshness Alert
```yaml
- alert: WeatherStationDataStale
  expr: (time() - last_fetch_time) > 300  # 5 minutes
  for: 2m
  labels:
    severity: warning
  annotations:
    summary: "Weather station {{ $labels.station_id }} has stale data"
    description: "No successful data fetch for {{ $value }} seconds"
```

### API Performance Alert
```yaml
- alert: WeatherStationSlowAPI
  expr: last_fetch_duration > 10  # 10 seconds
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Weather station {{ $labels.station_id }} API is slow"
    description: "API requests taking {{ $value }} seconds"
```

### Stuck Temperature Sensor
```yaml
- alert: WeatherStationTemperatureStuck
  expr: (time() - temperature_last_change) > 21600  # 6 hours
  for: 10m
  labels:
    severity: critical
  annotations:
    summary: "Weather station {{ $labels.station_id }} temperature sensor stuck"
    description: "Temperature unchanged for {{ $value }} seconds"
```

### Low Success Rate
```yaml
- alert: WeatherStationLowSuccessRate
  expr: increase(successful_requests_total[1h]) < 50  # Expected: ~60 requests/hour
  for: 15m
  labels:
    severity: warning
  annotations:
    summary: "Weather station {{ $labels.station_id }} low success rate"
    description: "Only {{ $value }} successful requests in the last hour"
```

## Troubleshooting

### No Recent Data (`last_fetch_time` is old)
**Possible Causes:**
- Network connectivity issues
- API key problems
- Service not running
- API endpoint down

**Debug Steps:**
1. Check service logs: `journalctl --user -u wunderground.service -f`
2. Test API manually: `curl "https://api.weather.com/v2/pws/observations/current?apiKey=XXX&stationId=ICAHOR23&format=json"`
3. Verify network connectivity: `ping api.weather.com`

### Slow API Requests (`last_fetch_duration` high)
**Possible Causes:**
- API server overload
- Network latency
- DNS resolution delays

**Debug Steps:**
1. Enable debug logging: `--debug true`
2. Check network latency: `ping api.weather.com`
3. Monitor trends over time

### Temperature Not Changing (`temperature_last_change` old)
**Possible Causes:**
- Faulty temperature sensor
- Station maintenance
- Calibration issues

**Debug Steps:**
1. Check station status on Weather Underground website
2. Compare with nearby stations
3. Verify other metrics are updating normally

## Configuration

### Enable Debug Logging
```bash
# For systemd service:
sudo systemctl --user edit wunderground.service

# Add:
[Service]
ExecStart=
ExecStart=/usr/bin/python3 wunderground.py --bind=127.0.0.1 --port=12100 --debug=true
```

### Service Management
```bash
# View current status
systemctl --user status wunderground.service

# View recent logs
journalctl --user -u wunderground.service --since "1 hour ago"

# Restart service
systemctl --user restart wunderground.service
```

---

**Note**: These metrics are only available when the service is running and successfully initialized. Missing metrics may indicate service startup issues.