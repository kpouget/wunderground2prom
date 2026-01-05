# Health Monitoring Metrics

This document describes the health monitoring metrics exposed by both the weather station exporter and river flow exporter.

## Overview

Both services expose health metrics to monitor service reliability, API performance, and data freshness. These metrics help detect issues before they cause service outages.

## Services

- **Weather Station Service** (port 12100): Monitors weather stations via Weather Underground API
- **River Flow Service** (port 12101): Monitors French river flow and height via Vigicrues API

## Weather Station Health Metrics

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

## River Flow Health Metrics

### `river_last_fetch_time{river="...", station="...", station_id="..."}`
- **Type**: Gauge (Unix timestamp)
- **Description**: Timestamp of the last successful data fetch from each river monitoring station
- **Updated**: Only when API request succeeds and returns valid data
- **Use Case**: Detect stale river data or communication issues with Vigicrues API

**Example Value**: `1704151200` (2024-01-01 20:00:00 UTC)

### `river_last_fetch_duration{river="...", station="...", station_id="..."}`
- **Type**: Gauge (seconds)
- **Description**: Average duration of the last successful API requests (flow + height)
- **Updated**: Only for successful requests (excludes timeouts/errors)
- **Use Case**: Monitor Vigicrues API performance and detect slowdowns

**Example Value**: `1.85` (1.85 seconds average for flow and height requests)

### `river_successful_requests_total{river="...", station="...", station_id="..."}`
- **Type**: Gauge (counter)
- **Description**: Total successful API requests since service startup (flow + height combined)
- **Updated**: Incremented by 2 for each complete station update (1 for flow, 1 for height)
- **Use Case**: Calculate success rates and request frequency

**Example Value**: `2880` (24 hours × 60 minutes × 2 requests = 2880 successful requests)

### `river_data_last_change{river="...", station="...", station_id="..."}`
- **Type**: Gauge (Unix timestamp)
- **Description**: Timestamp when river flow or height values last changed
- **Updated**: When either flow or height reading differs from previous value
- **Use Case**: Detect stuck sensors or data validation issues

**Example Value**: `1704151020` (2024-01-01 19:57:00 UTC)

## Accessing Metrics

### View All Weather Station Health Metrics
```bash
curl http://127.0.0.1:12100/metrics | grep -E "(last_fetch|successful_requests|temperature_last_change)"
```

### View All River Flow Health Metrics
```bash
curl http://127.0.0.1:12101/metrics | grep -E "(river_last_fetch|river_successful_requests|river_data_last_change)"
```

### View Specific Weather Station
```bash
curl http://127.0.0.1:12100/metrics | grep 'station_id="ICAHOR23"'
```

### Weather Station Dashboards
- **Station ICAHOR23** (Cahors): https://www.wunderground.com/dashboard/pws/ICAHOR23
- **Station IVAYRA1** (Vayrac): https://www.wunderground.com/dashboard/pws/IVAYRA1
- **Station ICOUBL3** (Coublevie): https://www.wunderground.com/dashboard/pws/ICOUBL3
- **Station IREVEL54** (Revel): https://www.wunderground.com/dashboard/pws/IREVEL54
- **Station IPAMPL52** (Pamplona): https://www.wunderground.com/dashboard/pws/IPAMPL52
- **Station IMANDELI41** (Mandeli): https://www.wunderground.com/dashboard/pws/IMANDELI41
- **Station KMAEASTB68** (East Boston): https://www.wunderground.com/dashboard/pws/KMAEASTB68
- **Station ITOKYO63** (Tokyo): https://www.wunderground.com/dashboard/pws/ITOKYO63
- **Template for any station**: `https://www.wunderground.com/dashboard/pws/[STATION_ID]`

### View Specific River Station
```bash
# View specific river
curl http://127.0.0.1:12101/metrics | grep 'river="Dordogne"'

# View specific stations by ID
curl http://127.0.0.1:12101/metrics | grep 'station_id="P230001001"'  # Dordogne Souillac
curl http://127.0.0.1:12101/metrics | grep 'station_id="P207002002"'  # Dordogne Carennac
curl http://127.0.0.1:12101/metrics | grep 'station_id="O823153002"'  # Lot Cahors
```

## Monitoring Examples

### Calculate Weather Station Data Freshness
```bash
# Time since last successful fetch (seconds)
echo "scale=0; $(date +%s) - $(curl -s http://127.0.0.1:12100/metrics | grep 'last_fetch_time{station_id="ICAHOR23"}' | cut -d' ' -f2)" | bc
```

### Calculate River Data Freshness
```bash
# Time since last successful fetch for Dordogne at Souillac (P230001001)
echo "scale=0; $(date +%s) - $(curl -s http://127.0.0.1:12101/metrics | grep 'river_last_fetch_time{.*station_id="P230001001"' | cut -d' ' -f2)" | bc

# Time since last successful fetch for Lot at Cahors (O823153002)
echo "scale=0; $(date +%s) - $(curl -s http://127.0.0.1:12101/metrics | grep 'river_last_fetch_time{.*station_id="O823153002"' | cut -d' ' -f2)" | bc
```

### Calculate Success Rates
```bash
# Weather station successful requests in last hour (assuming 60-second intervals)
echo "Weather success rate: $(curl -s http://127.0.0.1:12100/metrics | grep 'successful_requests_total{station_id="ICAHOR23"}' | cut -d' ' -f2)/60"

# River station successful requests in last hour (assuming 300-second intervals, 2 requests per cycle)
echo "Dordogne Souillac success rate: $(curl -s http://127.0.0.1:12101/metrics | grep 'river_successful_requests_total{.*station_id="P230001001"' | cut -d' ' -f2)/24"
echo "Lot Cahors success rate: $(curl -s http://127.0.0.1:12101/metrics | grep 'river_successful_requests_total{.*station_id="O823153002"' | cut -d' ' -f2)/24"
```

## Prometheus Alerting

### Weather Station Alerts

#### Data Freshness Alert
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

#### API Performance Alert
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

#### Stuck Temperature Sensor
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

#### Low Success Rate
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

### River Flow Alerts

#### River Data Freshness Alert
```yaml
- alert: RiverDataStale
  expr: (time() - river_last_fetch_time) > 600  # 10 minutes
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "River station {{ $labels.river }} {{ $labels.station }} has stale data"
    description: "No successful data fetch for {{ $value }} seconds"
```

#### River API Performance Alert
```yaml
- alert: RiverSlowAPI
  expr: river_last_fetch_duration > 15  # 15 seconds
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "River station {{ $labels.river }} {{ $labels.station }} API is slow"
    description: "API requests taking {{ $value }} seconds"
```

#### Stuck River Data
```yaml
- alert: RiverDataStuck
  expr: (time() - river_data_last_change) > 43200  # 12 hours
  for: 15m
  labels:
    severity: critical
  annotations:
    summary: "River station {{ $labels.river }} {{ $labels.station }} data stuck"
    description: "Flow/height unchanged for {{ $value }} seconds"
```

#### River Low Success Rate
```yaml
- alert: RiverLowSuccessRate
  expr: increase(river_successful_requests_total[1h]) < 20  # Expected: ~24 requests/hour (12 cycles × 2 requests)
  for: 20m
  labels:
    severity: warning
  annotations:
    summary: "River station {{ $labels.river }} {{ $labels.station }} low success rate"
    description: "Only {{ $value }} successful requests in the last hour"
```

## Troubleshooting

### Weather Station Issues

#### No Recent Data (`last_fetch_time` is old)
**Possible Causes:**
- Network connectivity issues
- API key problems
- Weather service not running
- API endpoint down

**Debug Steps:**
1. Check service logs: `journalctl --user -u wunderground.service -f`
2. Check station status: https://www.wunderground.com/dashboard/pws/ICAHOR23
3. Test API manually: `curl "https://api.weather.com/v2/pws/observations/current?apiKey=XXX&stationId=ICAHOR23&format=json"`
4. Verify network connectivity: `ping api.weather.com`

#### Slow API Requests (`last_fetch_duration` high)
**Possible Causes:**
- API server overload
- Network latency
- DNS resolution delays

**Debug Steps:**
1. Enable debug logging: `--debug true`
2. Check network latency: `ping api.weather.com`
3. Monitor trends over time

#### Temperature Not Changing (`temperature_last_change` old)
**Possible Causes:**
- Faulty temperature sensor
- Station maintenance
- Calibration issues

**Debug Steps:**
1. Check station status on Weather Underground website:
   - Station ICAHOR23: https://www.wunderground.com/dashboard/pws/ICAHOR23
   - Or for any station: https://www.wunderground.com/dashboard/pws/[STATION_ID]
2. Compare with nearby stations
3. Verify other metrics are updating normally

### River Flow Issues

#### No Recent River Data (`river_last_fetch_time` is old)
**Possible Causes:**
- Network connectivity issues
- River service not running
- Vigicrues API endpoint down
- Station maintenance

**Debug Steps:**
1. Check service logs: `journalctl --user -u river-flow.service -f`
2. Test API manually for each station:
   ```bash
   # Lot at Cahors (O823153002)
   curl "https://www.vigicrues.gouv.fr/services/observations.json/index.php?CdStationHydro=O823153002&GrdSerie=Q&FormatSortie=simple"

   # Dordogne at Carennac (P207002002)
   curl "https://www.vigicrues.gouv.fr/services/observations.json/index.php?CdStationHydro=P207002002&GrdSerie=Q&FormatSortie=simple"

   # Dordogne at Souillac (P230001001)
   curl "https://www.vigicrues.gouv.fr/services/observations.json/index.php?CdStationHydro=P230001001&GrdSerie=Q&FormatSortie=simple"
   ```
3. Verify network connectivity: `ping www.vigicrues.gouv.fr`

#### Slow River API Requests (`river_last_fetch_duration` high)
**Possible Causes:**
- Vigicrues server overload
- Network latency
- Large data responses

**Debug Steps:**
1. Enable debug logging: `--debug true`
2. Check network latency: `ping www.vigicrues.gouv.fr`
3. Monitor request patterns during peak hours

#### River Data Not Changing (`river_data_last_change` old)
**Possible Causes:**
- River flow/height sensors stuck
- Station maintenance or calibration
- Extreme weather conditions (drought/flood)

**Debug Steps:**
1. Check station status on Vigicrues website:
   - Lot at Cahors: https://www.vigicrues.gouv.fr/niv3-station.php?CdStationHydro=O823153002
   - Dordogne at Carennac: https://www.vigicrues.gouv.fr/niv3-station.php?CdStationHydro=P207002002
   - Dordogne at Souillac: https://www.vigicrues.gouv.fr/niv3-station.php?CdStationHydro=P230001001
2. Compare with nearby river stations
3. Verify both flow and height are updating normally
4. Check for rounding/stair pattern issues in data

## Configuration

### Enable Debug Logging

#### Weather Station Service
```bash
# For systemd service:
systemctl --user edit wunderground.service

# Add:
[Service]
ExecStart=
ExecStart=/usr/bin/python3 wunderground.py --bind=127.0.0.1 --port=12100 --debug=true
```

#### River Flow Service
```bash
# For systemd service:
systemctl --user edit river-flow.service

# Add:
[Service]
ExecStart=
ExecStart=/usr/bin/python3 river_flow.py --bind=127.0.0.1 --port=12101 --debug=true
```

### Service Management

#### Weather Station Service
```bash
# View current status
systemctl --user status wunderground.service

# View recent logs
journalctl --user -u wunderground.service --since "1 hour ago"

# Restart service
systemctl --user restart wunderground.service
```

#### River Flow Service
```bash
# View current status
systemctl --user status river-flow.service

# View recent logs
journalctl --user -u river-flow.service --since "1 hour ago"

# Restart service
systemctl --user restart river-flow.service
```

#### Both Services
```bash
# View status of both services
systemctl --user status wunderground.service river-flow.service

# View combined logs (last hour)
journalctl --user -u wunderground.service -u river-flow.service --since "1 hour ago"

# Restart both services
systemctl --user restart wunderground.service river-flow.service
```

---

**Note**: These metrics are only available when the respective services are running and successfully initialized. Missing metrics may indicate service startup issues.

## Quick Reference

### Service Ports
- **Weather Station**: `http://127.0.0.1:12100/metrics`
- **River Flow**: `http://127.0.0.1:12101/metrics`

### External Dashboards
**Weather Underground Stations:**
- **ICAHOR23** (Cahors): https://www.wunderground.com/dashboard/pws/ICAHOR23
- **IVAYRA1** (Vayrac): https://www.wunderground.com/dashboard/pws/IVAYRA1
- **ICOUBL3** (Coublevie): https://www.wunderground.com/dashboard/pws/ICOUBL3
- **IREVEL54** (Revel): https://www.wunderground.com/dashboard/pws/IREVEL54
- **IPAMPL52** (Pamplona): https://www.wunderground.com/dashboard/pws/IPAMPL52
- **IMANDELI41** (Mandeli): https://www.wunderground.com/dashboard/pws/IMANDELI41
- **KMAEASTB68** (East Boston): https://www.wunderground.com/dashboard/pws/KMAEASTB68
- **ITOKYO63** (Tokyo): https://www.wunderground.com/dashboard/pws/ITOKYO63

**Vigicrues River Monitoring:**
  - Lot at Cahors: https://www.vigicrues.gouv.fr/niv3-station.php?CdStationHydro=O823153002
  - Dordogne at Carennac: https://www.vigicrues.gouv.fr/niv3-station.php?CdStationHydro=P207002002
  - Dordogne at Souillac: https://www.vigicrues.gouv.fr/niv3-station.php?CdStationHydro=P230001001

### Current River Stations
- **Lot**: Cahors - Station ID: `O823153002`
- **Dordogne**: Carennac - Station ID: `P207002002`
- **Dordogne**: Souillac - Station ID: `P230001001`

### Update Intervals
- **Weather Station**: 60 seconds
- **River Flow**: 300 seconds (5 minutes)

### Quick Health Check Commands
```bash
# Check all river stations health
curl -s http://127.0.0.1:12101/metrics | grep -E "(river_last_fetch_time|river_successful_requests)" | grep -E "(O823153002|P207002002|P230001001)"

# Current river flow for all stations
curl -s http://127.0.0.1:12101/metrics | grep "river_flow{" | grep -E "(O823153002|P207002002|P230001001)"

# Current river height for all stations
curl -s http://127.0.0.1:12101/metrics | grep "river_height{" | grep -E "(O823153002|P207002002|P230001001)"
```