# Metrics Export Guide

This document explains how to expose and export metrics from Polymarket agents to monitoring systems.

## Prometheus

- Use the `prom-client` library to define and register metrics.
- Expose an HTTP endpoint (e.g. `/metrics`) that Prometheus can scrape.
- Configure your Prometheus server to scrape the agent endpoint at a suitable interval.

## StatsD

- Use a StatsD client (e.g. `hot-shots`) to send counters and histograms.
- Set the StatsD server address via environment variables.
- Prefix metric names with `agent_` to avoid naming collisions.

## Recommended metrics

- Message processing latency (histogram)
- Number of messages processed (counter)
- Error rate (counter)
- Queue length or backlog (gauge)

Proper metrics export enables better visibility into agent performance and reliability.
