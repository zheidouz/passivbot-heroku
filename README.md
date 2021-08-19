![Passivbot](docs/images/logo.png)

# Trading bot running on Bybit and Binance Futures

:warning: **Use at own risk** :warning:

## Overview

Passivbot is a trading bot written in Python to automate trading on exchanges.  
The philosophy behind the bot is to have a bot that you can simply run and forget about.  
It is observed that prices in a market will fluctuate up and down, creating opportunities for capitalizing on the noise.  
The bot's purpose is to automate the harvest.

Passivbot operates on spot or futures markets by listening to websocket stream of live trades,
automatically creating and cancelling limit buy and sell orders.

Because passivbot's live behavior is deterministic, it may be simulated on historical price data, using the included backtester.  
Also included is an optimizer, which finds better configurations by iterating thousands of backtests with different candidates.  
The bot can be controlled via Telegram.

There is no strategy that needs to built, it only needs a predefined configuration to run.

## Requirements

- Python >= 3.8
- [requirements.txt](requirements.txt) dependencies

## Pre-optimized configurations

A number of pre-optimized configurations for Passivbot can be found at https://github.com/JohnKearney1/PassivBot-Configurations.

## Documentation:

For more detailed information about Passivbot, you can look at the documentation on https://www.passivbot.com

## Support

[![Discord](https://img.shields.io/badge/Discord-7289DA?style=for-the-badge&logo=discord&logoColor=white)](https://discord.gg/QAF2H2UmzZ)

[![Telegram](https://img.shields.io/badge/Telegram-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white)](https://t.me/passivbot_futures)

## License

Released freely without conditions.
Anybody may copy, distribute, modify, use or misuse for commercial,
non-commercial, educational or non-educational purposes, censor,
claim as one's own or otherwise do whatever without permission from anybody.
