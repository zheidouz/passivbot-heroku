# Running the bot live

Once you've installed and configured the bot as desired, it's time to start your bot in live mode. This page explains
how you can start your bot, and anything relating to keeping the system running unattended.

## Usage

In order to start the bot in live mode, you will need two things:
1) setup your API-keys and (optionally) your telegram settings in the `api-keys.json` file in the root folder.
   The template file `api-keys.example.json` can be copied as a starting file. 
2) have the config file you want to use in live mode readily available for the bot (typically placed in `configs/live`)

!!! Warning
    Make sure you enable `futures` on the API key. Also, be aware that on Binance you have to complete a quiz before you
    can trade futures. Apart from that, you need to make sure there are funds present in the futures wallet.

You can use your favorite text editor to setup the account details in the `api-keys.json` file. There's a sample template
already available when you check out the repository, so you can simply put the required information in the expected places.

Please make not of the account name that is written in the `api-keys.json` file at the root level, you will need this for the next
step (e.g. `binance_01` in the template for example).

!!! Info
    You can name the account any way you want, just make sure you make of what you set it to, as it's used in both live mode, backtesting and optimize

To actually start the bot, you can use the following command:

```shell
python3 start_bot.py {account_name} {symbol} {path/to/config.json}
```

An actual command with the values filled in could look like this for example:

```shell
python3 start_bot.py binance_01 XMRUSDT configs/live/binance_xmrusdt.json
```

### Default configurations

There are a number of configurations provided by default in the repository. These configurations are optimized and
backtested over a longer period of time, and provide a good starting point for setting up your own perfect
configuration. You can find these configurations in the [configs/live](https://github.com/enarjord/passivbot/tree/master/configs/live) directory.

There is also a public repository available with a lot of optimized & backtested configurations on multiple coins at
[this](https://github.com/JohnKearney1/PassivBot-Configurations) github repository.

If you found a good config and want to share this configuration, please feel free to get in touch with the community to do so!

## Controlling the bot

While the bot is running, you can use Telegram to control the bot. This includes getting information on the results,
open trades as well as pausing the bot, and much more. You can read more on how to set up [Telegram here](telegram.md).

## Startup checks

When you start Passivbot, it will verify if there are no positions open on other coins. If there is an existing position
found on at least 1 other symbol, the bot will shut down. The reason for this is that the bot operates in cross-mode for futures,
which means that it will start influencing the existing position. If you want to, you can disable this check by setting
the configuration parameter `allow_sharing_wallet` to `false`.

When Passivbot is started, it will (if possible) set the position mode to `hedge` on the exchange, and set the leverage
to such a level that you do not run into errors about insufficient margin. To accomplish this, the configuration parameter
`pbr_limit` is taken into account to determine the appropriate leverage to set on the exchange.

## Stopping bot

!!! Warning
    Before stopping the bot, please make sure it is in an appropriate state, e.g. make sure there are no positions or orders open that will cause problems if left open for a longer period 

If you want to stop, you can achieve this by either:
* using the `/stop` button in Telegram (if configured), or
* by pressing `ctrl+c` in the terminal

!!! Info
    Please note that shutting down the bot properly may take a couple of seconds, as it needs time to properly detach from the websocket and shutdown the bot. When the bot is completely shut down, you will see a message that Telegram has been shut down, and another message that Passivbot has been shut down.

## Running unattended

Currently there is no active support for running passivbot as a service. Future development is likely to include this,
but for now for Unix-based systems it should be fairly straight forward to set this up. There are numerous tutorials
available on Google if you search for 'linux running python as a service'.

If you want to leave the bot running without requiring to have the terminal window open all the time, you can use tools
like [tmux](https://github.com/tmux/tmux), [screen](http://www.gnu.org/software/screen/manual/screen.html) or a similar utility.

In case you need any help, feel freee to reach out for help via one of the channels described in [Home](index.md).