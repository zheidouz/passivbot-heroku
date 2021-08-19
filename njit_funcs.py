import sys
import numpy as np


if '--nojit' in sys.argv:
    print('not using numba')

    def njit(pyfunc=None, **kwargs):
        def wrap(func):
            return func

        if pyfunc is not None:
            return wrap(pyfunc)
        else:
            return wrap
else:
    print('using numba')
    from numba import njit


@njit
def round_dynamic(n: float, d: int):
    if n == 0.0:
        return n
    return round(n, d - int(np.floor(np.log10(abs(n)))) - 1)


@njit
def round_up(n, step, safety_rounding=10) -> float:
    return np.round(np.ceil(np.round(n / step, safety_rounding)) * step, safety_rounding)


@njit
def round_dn(n, step, safety_rounding=10) -> float:
    return np.round(np.floor(np.round(n / step, safety_rounding)) * step, safety_rounding)


@njit
def round_(n, step, safety_rounding=10) -> float:
    return np.round(np.round(n / step) * step, safety_rounding)


@njit
def calc_diff(x, y):
    return abs(x - y) / abs(y)


@njit
def nan_to_0(x) -> float:
    return x if x == x else 0.0


@njit
def calc_min_entry_qty(price, inverse, qty_step, min_qty, min_cost) -> float:
    return min_qty if inverse else max(min_qty, round_up(min_cost / price if price > 0.0 else 0.0, qty_step))


@njit
def calc_max_entry_qty(entry_price, available_margin, inverse, qty_step, c_mult):
    return round_dn(cost_to_qty(available_margin, entry_price, inverse, c_mult), qty_step)


@njit
def cost_to_qty(cost, price, inverse, c_mult):
    return cost * price / c_mult if inverse else (cost / price if price > 0.0 else 0.0)


@njit
def qty_to_cost(qty, price, inverse, c_mult) -> float:
    return (abs(qty / price) if price > 0.0 else 0.0) * c_mult if inverse else abs(qty * price)


@njit
def calc_ema(alpha, alpha_, prev_ema, new_val) -> float:
    return prev_ema * alpha_ + new_val * alpha


@njit
def calc_bid_ask_thresholds(prices: np.ndarray, MAs: np.ndarray, iprc_const, iprc_MAr_coeffs):
    bids = np.zeros(len(prices))
    asks = np.zeros(len(prices))
    for i in range(len(prices)):
        ratios = np.append(prices[i], MAs[i][:-1]) / MAs[i]
        bids[i] = MAs[i].min() * (iprc_const[0] + eqf(ratios, iprc_MAr_coeffs[0]))
        asks[i] = MAs[i].max() * (iprc_const[1] + eqf(ratios, iprc_MAr_coeffs[1]))
    return bids, asks


@njit
def calc_samples(ticks: np.ndarray, sample_size_ms: int = 1000) -> np.ndarray:
    # ticks [[timestamp, qty, price]]
    sampled_timestamps = np.arange(ticks[0][0] // sample_size_ms * sample_size_ms,
                                   ticks[-1][0] // sample_size_ms * sample_size_ms + sample_size_ms,
                                   sample_size_ms)
    samples = np.zeros((len(sampled_timestamps), 3))
    samples[:, 0] = sampled_timestamps
    ts = sampled_timestamps[0]
    i = 0
    k = 0
    while True:
        if ts == samples[k][0]:
            samples[k][1] += ticks[i][1]
            samples[k][2] = ticks[i][2]
            i += 1
            if i >= len(ticks):
                break
            ts = ticks[i][0] // sample_size_ms * sample_size_ms
        else:
            k += 1
            if k >= len(samples):
                break
            samples[k][2] = samples[k - 1][2]
    return samples


@njit
def calc_emas(xs, spans):
    emas = np.zeros((len(xs), len(spans)))
    alphas = 2 / (spans + 1)
    alphas_ = 1 - alphas
    emas[0] = xs[0]
    for i in range(1, len(xs)):
        emas[i] = emas[i - 1] * alphas_ + xs[i] * alphas
    return emas


@njit
def calc_long_pnl(entry_price, close_price, qty, inverse, c_mult) -> float:
    if inverse:
        if entry_price == 0.0 or close_price == 0.0:
            return 0.0
        return abs(qty) * c_mult * (1.0 / entry_price - 1.0 / close_price)
    else:
        return abs(qty) * (close_price - entry_price)


@njit
def calc_shrt_pnl(entry_price, close_price, qty, inverse, c_mult) -> float:
    if inverse:
        if entry_price == 0.0 or close_price == 0.0:
            return 0.0
        return abs(qty) * c_mult * (1.0 / close_price - 1.0 / entry_price)
    else:
        return abs(qty) * (entry_price - close_price)


@njit
def calc_equity(balance, long_psize, long_pprice, shrt_psize, shrt_pprice, last_price, inverse, c_mult):
    equity = balance
    if long_pprice and long_psize:
        equity += calc_long_pnl(long_pprice, last_price, long_psize, inverse, c_mult)
    if shrt_pprice and shrt_psize:
        equity += calc_shrt_pnl(shrt_pprice, last_price, shrt_psize, inverse, c_mult)
    return equity


@njit
def calc_available_margin(balance,
                          long_psize,
                          long_pprice,
                          shrt_psize,
                          shrt_pprice,
                          last_price,
                          inverse, c_mult, max_leverage) -> float:
    used_margin = 0.0
    equity = balance
    if long_pprice and long_psize:
        equity += calc_long_pnl(long_pprice, last_price, long_psize, inverse, c_mult)
        used_margin += qty_to_cost(long_psize, long_pprice, inverse, c_mult)
    if shrt_pprice and shrt_psize:
        equity += calc_shrt_pnl(shrt_pprice, last_price, shrt_psize, inverse, c_mult)
        used_margin += qty_to_cost(shrt_psize, shrt_pprice, inverse, c_mult)
    return max(0.0, equity * max_leverage - used_margin)


@njit
def calc_new_psize_pprice(psize, pprice, qty, price, qty_step) -> (float, float):
    if qty == 0.0:
        return psize, pprice
    new_psize = round_(psize + qty, qty_step)
    if new_psize == 0.0:
        return 0.0, 0.0
    return new_psize, nan_to_0(pprice) * (psize / new_psize) + price * (qty / new_psize)


@njit
def eqf(vals: np.ndarray, coeffs: np.ndarray, minus: float = 1.0) -> float:
    return np.sum((vals ** 2 - minus) * coeffs[:, 0] + np.abs(vals - minus) * coeffs[:, 1])


@njit
def calc_long_orders(balance,
                     long_psize,
                     long_pprice,
                     highest_bid,
                     lowest_ask,
                     MA_band_lower,
                     MA_band_upper,
                     MA_ratios,
                     available_margin,
 
                     spot,
                     inverse,
                     qty_step,
                     price_step,
                     min_qty,
                     min_cost,
                     c_mult,
                     pbr_stop_loss,
                     pbr_limit,
                     iqty_const,
                     iprc_const,
                     rqty_const,
                     rprc_const,
                     markup_const,
                     iqty_MAr_coeffs,
                     iprc_MAr_coeffs,
                     rprc_PBr_coeffs,
                     rqty_MAr_coeffs,
                     rprc_MAr_coeffs,
                     markup_MAr_coeffs) -> ((float, float, float, float, str), (float, float, float, float, str)):
    entry_price = min(highest_bid, round_dn(MA_band_lower * (iprc_const + eqf(MA_ratios, iprc_MAr_coeffs)), price_step))
    if long_psize == 0.0 or (spot and (long_psize < calc_min_entry_qty(long_pprice, inverse, qty_step, min_qty, min_cost))):
        min_entry_qty = calc_min_entry_qty(entry_price, inverse, qty_step, min_qty, min_cost)
        max_entry_qty = cost_to_qty(min(balance * (pbr_limit + max(0.0, pbr_stop_loss)), available_margin),
                                    entry_price, inverse, c_mult)
        base_entry_qty = cost_to_qty(balance, entry_price, inverse, c_mult) * (iqty_const + eqf(MA_ratios, iqty_MAr_coeffs))
        entry_qty = max(min_entry_qty, round_dn(min(max_entry_qty, base_entry_qty), qty_step))
        entry_type = 'long_ientry'
        long_close = (0.0, 0.0, 'long_nclose')
    elif long_psize > 0.0:
        pbr = qty_to_cost(long_psize, long_pprice, inverse, c_mult) / balance
        entry_price = min(entry_price,
                          round_dn(long_pprice * (rprc_const + eqf(MA_ratios, rprc_MAr_coeffs) +
                                                  eqf(np.array([pbr]), rprc_PBr_coeffs, minus=0.0)), price_step))
        min_entry_qty = calc_min_entry_qty(entry_price, inverse, qty_step, min_qty, min_cost)
        max_entry_qty = cost_to_qty(min(balance * (pbr_limit + max(0.0, pbr_stop_loss) - pbr), available_margin),
                                    entry_price, inverse, c_mult)
        base_entry_qty = cost_to_qty(balance, entry_price, inverse, c_mult) * (iqty_const + eqf(MA_ratios, iqty_MAr_coeffs))
        entry_qty = round_dn(min(max_entry_qty,
                                 max(min_entry_qty,
                                     base_entry_qty + (long_psize * (rqty_const + eqf(MA_ratios, rqty_MAr_coeffs))))), qty_step)
        nclose_price = max(lowest_ask, round_up(long_pprice * (markup_const + eqf(MA_ratios, markup_MAr_coeffs)), price_step))
        if entry_qty < min_entry_qty:
            entry_qty = 0.0

        if pbr_stop_loss < 0.0:
            # v3.6.2 behavior
            close_price = max(lowest_ask, min(nclose_price, round_up(MA_band_upper, price_step)))
            close_type = 'long_nclose' if close_price > long_pprice else 'long_sclose'
            long_close = (-long_psize, close_price, close_type)
        elif pbr_stop_loss == 0.0:
            long_close = (-long_psize, nclose_price, 'long_nclose')
        else:
            # v3.6.1 behavior
            if pbr > pbr_limit:
                sclose_price = max(lowest_ask, round_up(MA_band_upper, price_step))
                sclose_qty = -min(long_psize, max(min_qty, round_dn(cost_to_qty(balance * min(1.0, pbr - pbr_limit),
                                                                                sclose_price, inverse, c_mult), qty_step)))
                if sclose_price >= nclose_price:
                    long_close = (-long_psize, nclose_price, 'long_nclose')
                else:
                    long_close = (sclose_qty, sclose_price, 'long_sclose')
            else:
                entry_qty = max(entry_qty, min_entry_qty)
                long_close = (-long_psize, nclose_price, 'long_nclose')
        entry_type = 'long_rentry'
    else:
        raise Exception('long psize is less than 0.0')

    if spot:
        if entry_qty != 0.0:
            equity = calc_equity(balance, long_psize, long_pprice, 0.0, 0.0, highest_bid, inverse, c_mult)
            excess_cost = max(0.0, qty_to_cost(long_psize + entry_qty, highest_bid, inverse, c_mult) - equity)
            if excess_cost:
                entry_qty = round_dn((qty_to_cost(entry_qty, entry_price, inverse, c_mult) - excess_cost) / entry_price, qty_step)
                if entry_qty < min_entry_qty:
                    entry_qty = 0.0
        if long_close[0] != 0.0:
            min_close_qty = calc_min_entry_qty(long_close[1], inverse, qty_step, min_qty, min_cost)
            close_qty = round_dn(min(long_psize, max(min_close_qty, abs(long_close[0]))), qty_step)
            if close_qty < min_close_qty:
                long_close = (0.0, 0.0, 'long_nclose')
            else:
                long_close = (-close_qty,) + long_close[1:]

    return (entry_qty, entry_price, entry_type), long_close


@njit
def calc_shrt_orders(balance,
                     shrt_psize,
                     shrt_pprice,
                     highest_bid,
                     lowest_ask,
                     MA_band_lower,
                     MA_band_upper,
                     MA_ratios,
                     available_margin,
 
                     spot,
                     inverse,
                     qty_step,
                     price_step,
                     min_qty,
                     min_cost,
                     c_mult,
                     pbr_stop_loss,
                     pbr_limit,
                     iqty_const,
                     iprc_const,
                     rqty_const,
                     rprc_const,
                     markup_const,
                     iqty_MAr_coeffs,
                     iprc_MAr_coeffs,
                     rprc_PBr_coeffs,
                     rqty_MAr_coeffs,
                     rprc_MAr_coeffs,
                     markup_MAr_coeffs) -> ((float, float, float, float, str), [(float, float, float, float, str)]):
    entry_price = max(lowest_ask, round_up(MA_band_upper * (iprc_const + eqf(MA_ratios, iprc_MAr_coeffs)), price_step))
    if shrt_psize == 0.0:
        min_entry_qty = calc_min_entry_qty(entry_price, inverse, qty_step, min_qty, min_cost)
        max_entry_qty = cost_to_qty(min(balance * (pbr_limit + max(0.0, pbr_stop_loss)), available_margin),
                                    entry_price, inverse, c_mult)
        base_entry_qty = cost_to_qty(balance, entry_price, inverse, c_mult) * (iqty_const + eqf(MA_ratios, iqty_MAr_coeffs))
        entry_qty = max(min_entry_qty, round_dn(min(max_entry_qty, base_entry_qty), qty_step))
        entry_type = 'shrt_ientry'
        shrt_close = (0.0, 0.0, 'shrt_nclose')
    elif shrt_psize < 0.0:
        pbr = qty_to_cost(shrt_psize, shrt_pprice, inverse, c_mult) / balance
        entry_price = max(entry_price,
                          round_up(shrt_pprice * (rprc_const + eqf(MA_ratios, rprc_MAr_coeffs) +
                                                  eqf(np.array([pbr]), rprc_PBr_coeffs, minus=0.0)), price_step))
        min_entry_qty = calc_min_entry_qty(entry_price, inverse, qty_step, min_qty, min_cost)
        max_entry_qty = cost_to_qty(min(balance * (pbr_limit + max(0.0, pbr_stop_loss) - pbr), available_margin),
                                    entry_price, inverse, c_mult)

        base_entry_qty = cost_to_qty(balance, entry_price, inverse, c_mult) * (iqty_const + eqf(MA_ratios, iqty_MAr_coeffs))
        entry_qty = round_dn(min(max_entry_qty,
                                 max(min_entry_qty,
                                     base_entry_qty + (-shrt_psize * (rqty_const + eqf(MA_ratios, rqty_MAr_coeffs))))), qty_step)
        nclose_price = min(highest_bid, round_dn(shrt_pprice * (markup_const + eqf(MA_ratios, markup_MAr_coeffs)), price_step))
        if entry_qty < min_entry_qty:
            entry_qty = 0.0
        if pbr_stop_loss < 0.0:
            # v3.6.2 behavior
            close_price = min(highest_bid, max(nclose_price, round_dn(MA_band_lower, price_step)))
            close_type = 'shrt_nclose' if close_price < shrt_pprice else 'shrt_sclose'
            shrt_close = (-shrt_psize, close_price, close_type)
        elif pbr_stop_loss == 0.0:
            shrt_close = (-shrt_psize, nclose_price, 'shrt_nclose')
        else:
            # v3.6.1 beahvior
            if pbr > pbr_limit:
                sclose_price = min(highest_bid, round_dn(MA_band_lower, price_step))
                sclose_qty = min(-shrt_psize, max(min_qty, round_dn(cost_to_qty(balance * min(1.0, pbr - pbr_limit),
                                                                                sclose_price, inverse, c_mult), qty_step)))
                if sclose_price <= nclose_price:
                    shrt_close = (-shrt_psize, nclose_price, 'shrt_nclose')
                else:
                    shrt_close = (sclose_qty, sclose_price, 'shrt_sclose')
            else:
                entry_qty = max(entry_qty, min_entry_qty)
                shrt_close = (-shrt_psize, nclose_price, 'shrt_nclose')

        entry_type = 'shrt_rentry'
    else:
        raise Exception('shrt psize is greater than 0.0. Please make sure you have funds available in your futures wallet')
    entry_qty = -entry_qty
    return (entry_qty, entry_price, entry_type), shrt_close


@njit
def calc_long_entry(
        balance,
        long_psize,
        long_pprice,
        long_pfills,
        highest_bid,

        spot,
        inverse,
        do_long,
        qty_step,
        price_step,
        min_qty,
        min_cost,
        c_mult,
        max_leverage,

        primary_iqty_pct,
        primary_ddown_factor,
        primary_grid_spacing,
        primary_spacing_pbr_coeffs,
        primary_pbr_limit,
        secondary_ddown_factor,
        secondary_grid_spacing,
        secondary_pbr_limit) -> (float, float, str):
    if do_long or long_psize > 0.0:
        long_entry_price = highest_bid
        long_base_entry_qty = round_dn(cost_to_qty(balance * primary_iqty_pct, long_entry_price, inverse, c_mult), qty_step)
        if long_psize == 0.0:# or (spot and (long_psize < calc_min_entry_qty(long_pprice, inverse, qty_step, min_qty, min_cost))):
            # todo: spot
            min_entry_qty = calc_min_entry_qty(long_entry_price, inverse, qty_step, min_qty, min_cost)
            max_entry_qty = round_dn(cost_to_qty(balance * primary_pbr_limit, long_entry_price, inverse, c_mult), qty_step)
            long_entry_qty = max(min_entry_qty, min(max_entry_qty, long_base_entry_qty))
            long_entry = (long_entry_qty, long_entry_price, 'long_ientry')
        elif long_psize > 0.0:
            pbr = qty_to_cost(long_psize, long_pprice, inverse, c_mult) / balance
            if pbr < primary_pbr_limit:
                grid_spacing = (1 - primary_grid_spacing) - eqf(np.array([pbr]), primary_spacing_pbr_coeffs, minus=0.0)
                long_entry_price = round_dn(long_pprice * grid_spacing, price_step)
                if long_pfills[-1][0] < 0.0: # means previous fill was a partial close
                    long_entry_price = max(long_entry_price, round_dn(long_pfills[-1][1] * (1 - primary_grid_spacing), price_step))
                    long_entry_comment = 'long_primary_rentry_after_partial_close'
                else:
                    long_entry_comment = 'long_primary_rentry'
                long_entry_price = min(highest_bid, long_entry_price)
                min_entry_qty = calc_min_entry_qty(long_entry_price, inverse, qty_step, min_qty, min_cost)
                max_entry_qty = round_dn(cost_to_qty(balance * primary_pbr_limit, long_entry_price, inverse, c_mult) - long_psize, qty_step)
                long_entry_qty = max(min_entry_qty, min(max_entry_qty, round_dn(long_base_entry_qty + long_psize * primary_ddown_factor, qty_step)))
                long_entry = (long_entry_qty, long_entry_price, long_entry_comment)
            elif pbr < secondary_pbr_limit:
                long_entry_price = min(highest_bid, round_dn(long_pprice * (1 - secondary_grid_spacing), price_step))
                min_entry_qty = calc_min_entry_qty(long_entry_price, inverse, qty_step, min_qty, min_cost)
                max_entry_qty = round_dn(cost_to_qty(balance * secondary_pbr_limit, long_entry_price, inverse, c_mult) - long_psize, qty_step)
                long_entry_qty = min(max_entry_qty, max(min_entry_qty, round_dn(long_base_entry_qty + long_psize * secondary_ddown_factor, qty_step)))
                if long_entry_qty < min_entry_qty:
                    long_entry = (0.0, 0.0, '')
                else:
                    long_entry = (long_entry_qty, long_entry_price, 'long_secondary_rentry')
            else:
                long_entry = (0.0, 0.0, '')
    else:
        long_entry = (0.0, 0.0, '')
    return long_entry


@njit
def calc_shrt_entry(
        balance,
        shrt_psize,
        shrt_pprice,
        shrt_pfills,
        lowest_ask,

        spot,
        inverse,
        do_shrt,
        qty_step,
        price_step,
        min_qty,
        min_cost,
        c_mult,
        max_leverage,

        primary_iqty_pct,
        primary_ddown_factor,
        primary_grid_spacing,
        primary_spacing_pbr_coeffs,
        primary_pbr_limit,
        secondary_ddown_factor,
        secondary_grid_spacing,
        secondary_pbr_limit) -> (float, float, str):
    if do_shrt or shrt_psize < 0.0:
        shrt_entry_price = lowest_ask
        shrt_base_entry_qty = round_dn(cost_to_qty(balance * primary_iqty_pct, shrt_entry_price, inverse, c_mult), qty_step)
        if shrt_psize == 0.0:# or (spot and (shrt_psize < calc_min_entry_qty(shrt_pprice, inverse, qty_step, min_qty, min_cost))):
            # todo: spot
            min_entry_qty = calc_min_entry_qty(shrt_entry_price, inverse, qty_step, min_qty, min_cost)
            max_entry_qty = round_dn(cost_to_qty(balance * primary_pbr_limit, shrt_entry_price, inverse, c_mult), qty_step)
            shrt_entry_qty = max(min_entry_qty, min(max_entry_qty, shrt_base_entry_qty))
            shrt_entry = (-shrt_entry_qty, shrt_entry_price, 'shrt_ientry')
        elif shrt_psize < 0.0:
            pbr = qty_to_cost(shrt_psize, shrt_pprice, inverse, c_mult) / balance
            if pbr < primary_pbr_limit:
                grid_spacing = (1 + primary_grid_spacing) + eqf(np.array([pbr]), primary_spacing_pbr_coeffs, minus=0.0)
                shrt_entry_price = round_dn(shrt_pprice * grid_spacing, price_step)
                if shrt_pfills[-1][0] > 0.0: # means previous fill was a partial close
                    shrt_entry_price = min(shrt_entry_price, round_up(shrt_pprice * (1 + primary_grid_spacing), price_step))
                    shrt_entry_comment = 'shrt_primary_rentry_after_partial_close'
                else:
                    shrt_entry_comment = 'shrt_primary_rentry'
                shrt_entry_price = max(lowest_ask, shrt_entry_price)
                min_entry_qty = calc_min_entry_qty(shrt_entry_price, inverse, qty_step, min_qty, min_cost)
                max_entry_qty = round_dn(cost_to_qty(balance * primary_pbr_limit, shrt_entry_price, inverse, c_mult) + shrt_psize, qty_step)
                shrt_entry_qty = max(min_entry_qty, min(max_entry_qty, round_dn(shrt_base_entry_qty - shrt_psize * primary_ddown_factor, qty_step)))
                shrt_entry = (-shrt_entry_qty, shrt_entry_price, shrt_entry_comment)
            elif pbr < secondary_pbr_limit:
                shrt_entry_price = min(lowest_ask, round_dn(shrt_pprice * (1 + secondary_grid_spacing), price_step))
                min_entry_qty = calc_min_entry_qty(shrt_entry_price, inverse, qty_step, min_qty, min_cost)
                max_entry_qty = round_dn(cost_to_qty(balance * secondary_pbr_limit, shrt_entry_price, inverse, c_mult) + shrt_psize, qty_step)
                shrt_entry_qty = min(max_entry_qty, max(min_entry_qty, round_dn(shrt_base_entry_qty - shrt_psize * secondary_ddown_factor, qty_step)))
                if shrt_entry_qty < min_entry_qty:
                    shrt_entry = (0.0, 0.0, '')
                else:
                    shrt_entry = (-shrt_entry_qty, shrt_entry_price, 'shrt_secondary_rentry')
            else:
                shrt_entry = (0.0, 0.0, '')
    else:
        shrt_entry = (0.0, 0.0, '')
    return shrt_entry


@njit
def calc_long_close_grid(long_psize,
                         long_pprice,
                         lowest_ask,

                         spot,
                         inverse,
                         qty_step,
                         price_step,
                         min_qty,
                         min_cost,
                         c_mult,
                         max_leverage,

                         min_markup,
                         markup_range,
                         n_close_orders) -> [(float, float, str)]:
            if long_psize == 0.0:
                return [(0.0, 0.0, '')]
            minm = long_pprice * (1 + min_markup)
            close_prices = []
            for p in np.linspace(minm, long_pprice * (1 + min_markup + markup_range), n_close_orders):
                price_ = max(lowest_ask, round_up(p, price_step))
                if len(close_prices) == 0 or price_ != close_prices[-1]:
                    close_prices.append(price_)
            if len(close_prices) == 0:
                return [(-long_psize, lowest_ask, 'long_nclose')]
            elif len(close_prices) == 1:
                return [(-long_psize, close_prices[0], 'long_nclose')]
            else:
                min_close_qty = calc_min_entry_qty(close_prices[0], inverse, qty_step, min_qty, min_cost)
                default_qty = round_dn(long_psize / len(close_prices), qty_step)
                if default_qty == 0.0:
                    return [(-long_psize, close_prices[0], 'long_nclose')]
                default_qty = max(min_close_qty, default_qty)
                long_closes = []
                remaining = long_psize
                for close_price in close_prices:
                    if not remaining or remaining / default_qty < 0.5:
                        break
                    close_qty = min(remaining, max(default_qty, min_close_qty))
                    long_closes.append((-close_qty, close_price, 'long_nclose'))
                    remaining = round_(remaining - close_qty, qty_step)
                if remaining:
                    if long_closes:
                        long_closes[-1] = (round_(long_closes[-1][0] - remaining, qty_step), long_closes[-1][1], long_closes[-1][2])
                    else:
                        long_closes = [(-long_psize, close_prices[0], 'long_nclose')]
                return long_closes


@njit
def calc_shrt_close_grid(shrt_psize,
                         shrt_pprice,
                         highest_bid,

                         spot,
                         inverse,
                         qty_step,
                         price_step,
                         min_qty,
                         min_cost,
                         c_mult,
                         max_leverage,

                         min_markup,
                         markup_range,
                         n_close_orders) -> [(float, float, str)]:
            if shrt_psize == 0.0:
                return [(0.0, 0.0, '')]
            minm = shrt_pprice * (1 - min_markup)
            close_prices = []
            for p in np.linspace(minm, shrt_pprice * (1 - min_markup - markup_range), n_close_orders):
                price_ = min(highest_bid, round_dn(p, price_step))
                if len(close_prices) == 0 or price_ != close_prices[-1]:
                    close_prices.append(price_)
            if len(close_prices) == 0:
                return [(-shrt_psize, highest_bid, 'shrt_nclose')]
            elif len(close_prices) == 1:
                return [(-shrt_psize, close_prices[0], 'shrt_nclose')]
            else:
                min_close_qty = calc_min_entry_qty(close_prices[-1], inverse, qty_step, min_qty, min_cost)
                default_qty = round_dn(-shrt_psize / len(close_prices), qty_step)
                if default_qty == 0.0:
                    return [(-shrt_psize, close_prices[0], 'shrt_nclose')]
                default_qty = max(min_close_qty, default_qty)
                shrt_closes = []
                remaining = -shrt_psize
                for close_price in close_prices:
                    if not remaining or remaining / default_qty < 0.5:
                        break
                    close_qty = min(remaining, default_qty)
                    shrt_closes.append((close_qty, close_price, 'shrt_nclose'))
                    remaining = round_(remaining - close_qty, qty_step)
                if remaining:
                    if shrt_closes:
                        shrt_closes[-1] = (round_(shrt_closes[-1][0] + remaining, qty_step), shrt_closes[-1][1], shrt_closes[-1][2])
                    else:
                        shrt_closes = [(-shrt_psize, close_prices[0], 'shrt_nclose')]
                return shrt_closes



@njit
def njit_backtest_no_ema_scalp(
        ticks,
        starting_balance,
        latency_simulation_ms,
        maker_fee,
        spot,
        hedge_mode,
        inverse,
        do_long,
        do_shrt,
        qty_step,
        price_step,
        min_qty,
        min_cost,
        c_mult,
        max_leverage,
        primary_iqty_pct,
        primary_ddown_factor,
        primary_grid_spacing,
        primary_spacing_pbr_coeffs,
        primary_pbr_limit,
        secondary_ddown_factor,
        secondary_grid_spacing,
        secondary_pbr_limit,
        min_markup,
        markup_range,
        n_close_orders):

    timestamps = ticks[:, 0]
    qtys = ticks[:, 1]
    prices = ticks[:, 2]

    balance = equity = starting_balance
    long_psize, long_pprice, shrt_psize, shrt_pprice = 0.0, 0.0, 0.0, 0.0
    next_update_ts = 0
    fills = []
    long_pfills = [(0.0, 0.0)] # fills since initial entry, resets when whole pos is closed
    shrt_pfills = [(0.0, 0.0)]

    long_entry = shrt_entry = (0.0, 0.0, '')
    long_closes = shrt_closes = [(0.0, 0.0, '')]
    bkr_price, available_margin = 0.0, 0.0

    prev_k = 0
    closest_bkr = 1.0
    lowest_eqbal_ratio = 1.0

    for k in range(len(prices)):
        if qtys[k] == 0.0:
            continue

        closest_bkr = min(closest_bkr, calc_diff(bkr_price, prices[k]))
        if timestamps[k] >= next_update_ts:
            # simulate small delay between bot and exchange
            long_entry = calc_long_entry(balance, long_psize, long_pprice, long_pfills, prices[k], spot, inverse,
                                         do_long, qty_step, price_step, min_qty, min_cost, c_mult,
                                         max_leverage, primary_iqty_pct[0], primary_ddown_factor[0],
                                         primary_grid_spacing[0], primary_spacing_pbr_coeffs[0],
                                         primary_pbr_limit[0], secondary_ddown_factor[0], secondary_grid_spacing[0],
                                         secondary_pbr_limit[0])
            shrt_entry = calc_shrt_entry(balance, shrt_psize, shrt_pprice, shrt_pfills, prices[k], spot, inverse,
                                         do_shrt, qty_step, price_step, min_qty, min_cost, c_mult,
                                         max_leverage, primary_iqty_pct[1], primary_ddown_factor[1],
                                         primary_grid_spacing[1], primary_spacing_pbr_coeffs[1],
                                         primary_pbr_limit[1], secondary_ddown_factor[1], secondary_grid_spacing[1],
                                         secondary_pbr_limit[1])
            long_closes = calc_long_close_grid(long_psize, long_pprice, prices[k], spot, inverse, qty_step,
                                               price_step, min_qty, min_cost, c_mult, max_leverage, min_markup[0],
                                               markup_range[0], n_close_orders[0])
            shrt_closes = calc_shrt_close_grid(shrt_psize, shrt_pprice, prices[k], spot, inverse, qty_step,
                                               price_step, min_qty, min_cost, c_mult, max_leverage, min_markup[1],
                                               markup_range[1], n_close_orders[1])

            equity = balance + calc_upnl(long_psize, long_pprice, shrt_psize, shrt_pprice,
                                         prices[k], inverse, c_mult)
            lowest_eqbal_ratio = min(lowest_eqbal_ratio, equity / balance)
            next_update_ts = timestamps[k] + 5000
            prev_k = k

            if equity / starting_balance < 0.1:
                # break if 90% of starting balance is lost
                return fills, (False, lowest_eqbal_ratio, closest_bkr)

            if closest_bkr < 0.06:
                # consider bankruptcy within 6% as liquidation
                if long_psize != 0.0:
                    fee_paid = -qty_to_cost(long_psize, long_pprice, inverse, c_mult) * maker_fee
                    pnl = calc_long_pnl(long_pprice, prices[k], -long_psize, inverse, c_mult)
                    balance = 0.0
                    equity = 0.0
                    long_psize, long_pprice = 0.0, 0.0
                    fills.append((k, timestamps[k], pnl, fee_paid, balance, equity,
                                  0.0, -long_psize, prices[k], 0.0, 0.0, 'long_bankruptcy'))
                if shrt_psize != 0.0:

                    fee_paid = -qty_to_cost(shrt_psize, shrt_pprice, inverse, c_mult) * maker_fee
                    pnl = calc_shrt_pnl(shrt_pprice, prices[k], -shrt_psize, inverse, c_mult)
                    balance, equity = 0.0, 0.0
                    shrt_psize, shrt_pprice = 0.0, 0.0
                    fills.append((k, timestamps[k], pnl, fee_paid, balance, equity,
                                  0.0, -shrt_psize, prices[k], 0.0, 0.0, 'shrt_bankruptcy'))

                return fills, (False, lowest_eqbal_ratio, closest_bkr)

        if long_entry[0] > 0.0 and prices[k] < long_entry[1]:
            long_pfills.append((long_entry[0], long_entry[1]))
            long_psize, long_pprice = calc_new_psize_pprice(long_psize, long_pprice, long_entry[0],
                                                            long_entry[1], qty_step)
            fee_paid = -qty_to_cost(long_entry[0], long_entry[1], inverse, c_mult) * maker_fee
            balance += fee_paid
            equity = calc_equity(balance, long_psize, long_pprice, shrt_psize, shrt_pprice, prices[k], inverse, c_mult)
            pbr = qty_to_cost(long_psize, long_pprice, inverse, c_mult) / balance
            fills.append((k, timestamps[k], 0.0, fee_paid, balance, equity, pbr,
                          long_entry[0], long_entry[1], long_psize, long_pprice, long_entry[2]))
            next_update_ts = min(next_update_ts, timestamps[k] + latency_simulation_ms)
            long_entry = calc_long_entry(balance, long_psize, long_pprice, long_pfills, prices[prev_k], spot, inverse,
                                         do_long, qty_step, price_step, min_qty, min_cost, c_mult,
                                         max_leverage, primary_iqty_pct[0], primary_ddown_factor[0],
                                         primary_grid_spacing[0], primary_spacing_pbr_coeffs[0],
                                         primary_pbr_limit[0], secondary_ddown_factor[0], secondary_grid_spacing[0],
                                         secondary_pbr_limit[0])
        while shrt_psize < 0.0 and shrt_closes and shrt_closes[0][0] > 0.0 and prices[k] < shrt_closes[0][1]:
            shrt_close_qty = shrt_closes[0][0]
            new_shrt_psize = round_(shrt_psize + shrt_close_qty, qty_step)
            if new_shrt_psize > 0.0:
                print('warning: shrt close qty greater than shrt psize')
                print('shrt_psize', shrt_psize)
                print('shrt_pprice', shrt_pprice)
                print('shrt_closes[0]', shrt_closes[0])
                shrt_close_qty = -shrt_psize
                new_shrt_psize, shrt_pprice = 0.0, 0.0
            if new_shrt_psize == 0.0:
                shrt_pfills = [(0.0, 0.0)]
            else:
                shrt_pfills.append((shrt_close_qty, shrt_closes[0][1]))
            shrt_psize = new_shrt_psize
            fee_paid = -qty_to_cost(shrt_close_qty, shrt_closes[0][1], inverse, c_mult) * maker_fee
            pnl = calc_shrt_pnl(shrt_pprice, shrt_closes[0][1], shrt_close_qty, inverse, c_mult)
            balance += fee_paid + pnl
            equity = calc_equity(balance, long_psize, long_pprice, shrt_psize, shrt_pprice, prices[k], inverse, c_mult)
            pbr = qty_to_cost(shrt_psize, shrt_pprice, inverse, c_mult) / balance
            fills.append((k, timestamps[k], pnl, fee_paid, balance, equity, pbr,
                          shrt_close_qty, shrt_closes[0][1], shrt_psize, shrt_pprice, shrt_closes[0][2]))
            next_update_ts = min(next_update_ts, timestamps[k] + latency_simulation_ms)
            shrt_closes = shrt_closes[1:]
        if shrt_entry[0] < 0.0 and prices[k] > shrt_entry[1]:
            shrt_pfills.append((shrt_entry[0], shrt_entry[1]))
            shrt_psize, shrt_pprice = calc_new_psize_pprice(shrt_psize, shrt_pprice, shrt_entry[0],
                                                            shrt_entry[1], qty_step)
            fee_paid = -qty_to_cost(shrt_entry[0], shrt_entry[1], inverse, c_mult) * maker_fee
            balance += fee_paid
            equity = calc_equity(balance, long_psize, long_pprice, shrt_psize, shrt_pprice, prices[k], inverse, c_mult)
            pbr = qty_to_cost(shrt_psize, shrt_pprice, inverse, c_mult) / balance
            fills.append((k, timestamps[k], 0.0, fee_paid, balance, equity, pbr,
                          shrt_entry[0], shrt_entry[1], shrt_psize, shrt_pprice, shrt_entry[2]))
            next_update_ts = min(next_update_ts, timestamps[k] + latency_simulation_ms)
            shrt_entry = calc_shrt_entry(balance, shrt_psize, shrt_pprice, shrt_pfills, prices[prev_k], spot, inverse,
                                         do_shrt, qty_step, price_step, min_qty, min_cost, c_mult,
                                         max_leverage, primary_iqty_pct[1], primary_ddown_factor[1],
                                         primary_grid_spacing[1], primary_spacing_pbr_coeffs[1],
                                         primary_pbr_limit[1], secondary_ddown_factor[1], secondary_grid_spacing[1],
                                         secondary_pbr_limit[1])
        while long_psize != 0.0 and long_closes and long_closes[0][0] != 0.0 and prices[k] > long_closes[0][1]:
            long_close_qty = long_closes[0][0]
            new_long_psize = round_(long_psize + long_close_qty, qty_step)
            if new_long_psize < 0.0:
                print('warning: long close qty greater than long psize')
                print('long_psize', long_psize)
                print('long_pprice', long_pprice)
                print('long_closes[0]', long_closes[0])
                long_close_qty = -long_psize
                new_long_psize, long_pprice = 0.0, 0.0
            if new_long_psize == 0.0:
                long_pfills = [(0.0, 0.0)]
            else:
                long_pfills.append((long_close_qty, long_closes[0][1]))
            long_psize = new_long_psize
            fee_paid = -qty_to_cost(long_close_qty, long_closes[0][1], inverse, c_mult) * maker_fee
            pnl = calc_long_pnl(long_pprice, long_closes[0][1], long_close_qty, inverse, c_mult)
            balance += fee_paid + pnl
            equity = calc_equity(balance, long_psize, long_pprice, shrt_psize, shrt_pprice, prices[k], inverse, c_mult)
            pbr = qty_to_cost(long_psize, long_pprice, inverse, c_mult) / balance
            fills.append((k, timestamps[k], pnl, fee_paid, balance, equity, pbr,
                          long_close_qty, long_closes[0][1], long_psize, long_pprice, long_closes[0][2]))
            next_update_ts = min(next_update_ts, timestamps[k] + latency_simulation_ms)
            long_closes = long_closes[1:]
    return fills, (True, lowest_eqbal_ratio, closest_bkr)


@njit
def calc_upnl(long_psize,
              long_pprice,
              shrt_psize,
              shrt_pprice,
              last_price,
              inverse, c_mult):
    return calc_long_pnl(long_pprice, last_price, long_psize, inverse, c_mult) + \
           calc_shrt_pnl(shrt_pprice, last_price, shrt_psize, inverse, c_mult)


@njit
def calc_orders(balance,
                long_psize,
                long_pprice,
                shrt_psize,
                shrt_pprice,
                highest_bid,
                lowest_ask,
                last_price,
                MAs,
 
                spot,
                hedge_mode,
                inverse,
                do_long,
                do_shrt,
                qty_step,
                price_step,
                min_qty,
                min_cost,
                c_mult,
                max_leverage,
                spans,
                pbr_stop_loss,
                pbr_limit,
                iqty_const,
                iprc_const,
                rqty_const,
                rprc_const,
                markup_const,
                iqty_MAr_coeffs,
                iprc_MAr_coeffs,
                rprc_PBr_coeffs,
                rqty_MAr_coeffs,
                rprc_MAr_coeffs,
                markup_MAr_coeffs):
    MA_ratios = np.append(last_price, MAs[:-1]) / MAs
    MA_band_lower = MAs.min()
    MA_band_upper = MAs.max()
    available_margin = calc_available_margin(balance, long_psize, long_pprice, shrt_psize, shrt_pprice,
                                             last_price, inverse, c_mult, max_leverage)
    if hedge_mode:
        do_long_ = do_long
        do_shrt_ = do_shrt
    else:
        no_pos = long_psize == 0.0 and shrt_psize == 0.0
        do_long_ = (no_pos and do_long) or long_psize != 0.0
        do_shrt_ = (no_pos and do_shrt) or shrt_psize != 0.0
    long_entry, long_close = calc_long_orders(balance,
                     long_psize,
                     long_pprice,
                     highest_bid,
                     lowest_ask,
                     MA_band_lower,
                     MA_band_upper,
                     MA_ratios,
                     available_margin,

                     spot,
                     inverse,
                     qty_step,
                     price_step,
                     min_qty,
                     min_cost,
                     c_mult,
                     pbr_stop_loss[0],
                     pbr_limit[0],
                     iqty_const[0],
                     iprc_const[0],
                     rqty_const[0],
                     rprc_const[0],
                     markup_const[0],
                     iqty_MAr_coeffs[0],
                     iprc_MAr_coeffs[0],
                     rprc_PBr_coeffs[0],
                     rqty_MAr_coeffs[0],
                     rprc_MAr_coeffs[0],
                     markup_MAr_coeffs[0]) if (spot or do_long_) else ((0.0, 0.0, ''), (0.0, 0.0, ''))
    shrt_entry, shrt_close = calc_shrt_orders(balance,
                     shrt_psize,
                     shrt_pprice,
                     highest_bid,
                     lowest_ask,
                     MA_band_lower,
                     MA_band_upper,
                     MA_ratios,
                     available_margin,

                     spot,
                     inverse,
                     qty_step,
                     price_step,
                     min_qty,
                     min_cost,
                     c_mult,
                     pbr_stop_loss[1],
                     pbr_limit[1],
                     iqty_const[1],
                     iprc_const[1],
                     rqty_const[1],
                     rprc_const[1],
                     markup_const[1],
                     iqty_MAr_coeffs[1],
                     iprc_MAr_coeffs[1],
                     rprc_PBr_coeffs[1],
                     rqty_MAr_coeffs[1],
                     rprc_MAr_coeffs[1],
                     markup_MAr_coeffs[1]) if (do_shrt_ and not spot) else ((0.0, 0.0, ''), (0.0, 0.0, ''))
    bkr_price = calc_bankruptcy_price(balance, long_psize, long_pprice, shrt_psize, shrt_pprice, inverse, c_mult)
    return long_entry, shrt_entry, long_close, shrt_close, bkr_price, available_margin



@njit
def calc_emas_last(xs, spans):
    alphas = 2.0 / (spans + 1.0)
    alphas_ = 1.0 - alphas
    emas = np.repeat(xs[0], len(spans))
    for i in range(1, len(xs)):
        emas = emas * alphas_ + xs[i] * alphas
    return emas


@njit
def njit_backtest(ticks: np.ndarray,
                  starting_balance,
                  latency_simulation_ms,
                  maker_fee,
                  spot,
                  hedge_mode,
                  inverse,
                  do_long,
                  do_shrt,
                  qty_step,
                  price_step,
                  min_qty,
                  min_cost,
                  c_mult,
                  max_leverage,
                  spans,
                  pbr_stop_loss,
                  pbr_limit,
                  iqty_const,
                  iprc_const,
                  rqty_const,
                  rprc_const,
                  markup_const,
                  iqty_MAr_coeffs,
                  iprc_MAr_coeffs,
                  rprc_PBr_coeffs,
                  rqty_MAr_coeffs,
                  rprc_MAr_coeffs,
                  markup_MAr_coeffs):

    timestamps = ticks[:, 0]
    qtys = ticks[:, 1]
    prices = ticks[:, 2]
    static_params = (spot, hedge_mode, inverse, do_long, do_shrt, qty_step, price_step, min_qty, min_cost,
                     c_mult, max_leverage, spans, pbr_stop_loss, pbr_limit, iqty_const, iprc_const,
                     rqty_const, rprc_const, markup_const, iqty_MAr_coeffs, iprc_MAr_coeffs, rprc_PBr_coeffs,
                     rqty_MAr_coeffs, rprc_MAr_coeffs, markup_MAr_coeffs)

    balance = equity = starting_balance
    long_psize, long_pprice, shrt_psize, shrt_pprice = 0.0, 0.0, 0.0, 0.0
    next_update_ts = 0
    fills = []

    long_entry = shrt_entry = long_close = shrt_close = (0.0, 0.0, '')
    bkr_price, available_margin = 0.0, 0.0

    prev_k = 0
    closest_bkr = 1.0
    lowest_eqbal_ratio = 1.0
    # spans are in minutes, convert to sample size
    spans = np.array([span / ((timestamps[1] - timestamps[0]) / (1000 * 60)) for span in spans])

    alphas = 2.0 / (spans + 1.0)
    alphas_ = 1.0 - alphas
    start_idx = int(round(spans.max()))
    MAs = calc_emas_last(prices[:start_idx], spans)
    for k in range(start_idx, len(prices)):
        new_MAs = MAs * alphas_ + prices[k] * alphas
        if qtys[k] == 0.0:
            MAs = new_MAs
            continue

        closest_bkr = min(closest_bkr, calc_diff(bkr_price, prices[k]))
        if timestamps[k] >= next_update_ts:
            # simulate small delay between bot and exchange
            long_entry, shrt_entry, long_close, shrt_close, bkr_price, available_margin = calc_orders(
                balance,
                long_psize,
                long_pprice,
                shrt_psize,
                shrt_pprice,
                prices[k],
                prices[k],
                prices[k],
                MAs,

                *static_params)
            equity = balance + calc_upnl(long_psize, long_pprice, shrt_psize, shrt_pprice,
                                         prices[k], inverse, c_mult)
            lowest_eqbal_ratio = min(lowest_eqbal_ratio, equity / balance)
            next_update_ts = timestamps[k] + 5000
            prev_k = k
            prev_MAs = MAs

            if equity / starting_balance < 0.1:
                # break if 90% of starting balance is lost
                return fills, (False, lowest_eqbal_ratio, closest_bkr)

            if closest_bkr < 0.06:
                # consider bankruptcy within 6% as liquidation
                if long_psize != 0.0:
                    fee_paid = -qty_to_cost(long_psize, long_pprice, inverse, c_mult) * maker_fee
                    pnl = calc_long_pnl(long_pprice, prices[k], -long_psize, inverse, c_mult)
                    balance = 0.0
                    equity = 0.0
                    long_psize, long_pprice = 0.0, 0.0
                    fills.append((k, timestamps[k], pnl, fee_paid, balance, equity,
                                  0.0, -long_psize, prices[k], 0.0, 0.0, 'long_bankruptcy'))
                if shrt_psize != 0.0:

                    fee_paid = -qty_to_cost(shrt_psize, shrt_pprice, inverse, c_mult) * maker_fee
                    pnl = calc_shrt_pnl(shrt_pprice, prices[k], -shrt_psize, inverse, c_mult)
                    balance, equity = 0.0, 0.0
                    shrt_psize, shrt_pprice = 0.0, 0.0
                    fills.append((k, timestamps[k], pnl, fee_paid, balance, equity,
                                  0.0, -shrt_psize, prices[k], 0.0, 0.0, 'shrt_bankruptcy'))

                return fills, (False, lowest_eqbal_ratio, closest_bkr)

        if long_entry[0] > 0.0 and prices[k] < long_entry[1]:
            if qtys[k] < long_entry[0]:
                partial_fill = True
                long_entry_qty = qtys[k]
                long_entry_comment = long_entry[2] + '_partial'
            else:
                partial_fill = False
                long_entry_qty = long_entry[0]
                long_entry_comment = long_entry[2] + '_full'
            long_psize, long_pprice = calc_new_psize_pprice(long_psize, long_pprice, long_entry_qty,
                                                            long_entry[1], qty_step)
            fee_paid = -qty_to_cost(long_entry_qty, long_entry[1], inverse, c_mult) * maker_fee
            balance += fee_paid
            equity = calc_equity(balance, long_psize, long_pprice, shrt_psize, shrt_pprice, prices[k], inverse, c_mult)
            pbr = qty_to_cost(long_psize, long_pprice, inverse, c_mult) / balance
            fills.append((k, timestamps[k], 0.0, fee_paid, balance, equity, pbr,
                          long_entry_qty, long_entry[1], long_psize, long_pprice, long_entry_comment))
            next_update_ts = min(next_update_ts, timestamps[k] + latency_simulation_ms)
            if partial_fill:
                long_entry = (round_(long_entry[0] - long_entry_qty, qty_step), long_entry[1], long_entry_comment)
            else:
                long_entry, _ = calc_long_orders(balance,
                                                 long_psize,
                                                 long_pprice,
                                                 prices[prev_k],
                                                 prices[prev_k],
                                                 prev_MAs.min(),
                                                 prev_MAs.max(),
                                                 np.append(prices[prev_k], prev_MAs[:-1]) / prev_MAs,
                                                 available_margin,

                                                 spot,
                                                 inverse,
                                                 qty_step,
                                                 price_step,
                                                 min_qty,
                                                 min_cost,
                                                 c_mult,
                                                 pbr_stop_loss[0],
                                                 pbr_limit[0],
                                                 iqty_const[0],
                                                 iprc_const[0],
                                                 rqty_const[0],
                                                 rprc_const[0],
                                                 markup_const[0],
                                                 iqty_MAr_coeffs[0],
                                                 iprc_MAr_coeffs[0],
                                                 rprc_PBr_coeffs[0],
                                                 rqty_MAr_coeffs[0],
                                                 rprc_MAr_coeffs[0],
                                                 markup_MAr_coeffs[0])
        if shrt_psize < 0.0 and shrt_close[0] > 0.0 and prices[k] < shrt_close[1]:
            if qtys[k] < shrt_close[0]:
                partial_fill = True
                shrt_close_comment = shrt_close[2] + '_partial'
                shrt_close_qty = qtys[k]
            else:
                partial_fill = False
                shrt_close_comment = shrt_close[2] + '_full'
                shrt_close_qty = shrt_close[0]
            new_shrt_psize = round_(shrt_psize + shrt_close_qty, qty_step)
            if new_shrt_psize > 0.0:
                print('warning: shrt close qty greater than shrt psize')
                print('shrt_psize', shrt_psize)
                print('shrt_pprice', shrt_pprice)
                print('shrt_close', shrt_close)
                shrt_close_qty = -shrt_psize
                new_shrt_psize, shrt_pprice = 0.0, 0.0
            shrt_psize = new_shrt_psize
            fee_paid = -qty_to_cost(shrt_close_qty, shrt_close[1], inverse, c_mult) * maker_fee
            pnl = calc_shrt_pnl(shrt_pprice, shrt_close[1], shrt_close_qty, inverse, c_mult)
            balance += fee_paid + pnl
            equity = calc_equity(balance, long_psize, long_pprice, shrt_psize, shrt_pprice, prices[k], inverse, c_mult)
            pbr = qty_to_cost(shrt_psize, shrt_pprice, inverse, c_mult) / balance
            fills.append((k, timestamps[k], pnl, fee_paid, balance, equity, pbr,
                          shrt_close_qty, shrt_close[1], shrt_psize, shrt_pprice, shrt_close_comment))
            next_update_ts = min(next_update_ts, timestamps[k] + latency_simulation_ms)
            if partial_fill:
                shrt_close = (shrt_close[0] - shrt_close_qty, shrt_close[1], shrt_close_comment)
            else:
                shrt_close = (0.0, 0.0, '')
        if shrt_entry[0] != 0.0 and prices[k] > shrt_entry[1]:
            if qtys[k] < -shrt_entry[0]:
                partial_fill = True
                shrt_entry_comment = shrt_entry[2] + '_partial'
                shrt_entry_qty = -qtys[k]
            else:
                partial_fill = False
                shrt_entry_comment = shrt_entry[2] + '_full'
                shrt_entry_qty = shrt_entry[0]
            shrt_psize, shrt_pprice = calc_new_psize_pprice(shrt_psize, shrt_pprice, shrt_entry_qty,
                                                            shrt_entry[1], qty_step)
            fee_paid = -qty_to_cost(shrt_entry_qty, shrt_entry[1], inverse, c_mult) * maker_fee
            balance += fee_paid
            equity = calc_equity(balance, long_psize, long_pprice, shrt_psize, shrt_pprice, prices[k], inverse, c_mult)
            pbr = qty_to_cost(shrt_psize, shrt_pprice, inverse, c_mult) / balance
            fills.append((k, timestamps[k], 0.0, fee_paid, balance, equity, pbr,
                          shrt_entry_qty, shrt_entry[1], shrt_psize, shrt_pprice, shrt_entry_comment))
            next_update_ts = min(next_update_ts, timestamps[k] + latency_simulation_ms)
            if partial_fill:
                shrt_entry = (shrt_entry[0] - shrt_entry_qty, shrt_entry[1], shrt_entry_comment)
            else:
                shrt_entry, _ = calc_shrt_orders(balance,
                                                 shrt_psize,
                                                 shrt_pprice,
                                                 prices[prev_k],
                                                 prices[prev_k],
                                                 prev_MAs.min(),
                                                 prev_MAs.max(),
                                                 np.append(prices[prev_k], prev_MAs[:-1]) / prev_MAs,
                                                 available_margin,

                                                 spot,
                                                 inverse,
                                                 qty_step,
                                                 price_step,
                                                 min_qty,
                                                 min_cost,
                                                 c_mult,
                                                 pbr_stop_loss[1],
                                                 pbr_limit[1],
                                                 iqty_const[1],
                                                 iprc_const[1],
                                                 rqty_const[1],
                                                 rprc_const[1],
                                                 markup_const[1],
                                                 iqty_MAr_coeffs[1],
                                                 iprc_MAr_coeffs[1],
                                                 rprc_PBr_coeffs[1],
                                                 rqty_MAr_coeffs[1],
                                                 rprc_MAr_coeffs[1],
                                                 markup_MAr_coeffs[1])
        if long_psize != 0.0 and long_close[0] != 0.0 and prices[k] > long_close[1]:
            if qtys[k] < -long_close[0]:
                partial_fill = True
                long_close_comment = long_close[2] + '_partial'
                long_close_qty = -qtys[k]
            else:
                partial_fill = False
                long_close_comment = long_close[2] + '_full'
                long_close_qty = long_close[0]
            new_long_psize = round_(long_psize + long_close_qty, qty_step)
            if new_long_psize < 0.0:
                print('warning: long close qty greater than long psize')
                print('long_psize', long_psize)
                print('long_pprice', long_pprice)
                print('long_close', long_close)
                long_close_qty = -long_psize
                new_long_psize, long_pprice = 0.0, 0.0
            long_psize = new_long_psize
            fee_paid = -qty_to_cost(long_close_qty, long_close[1], inverse, c_mult) * maker_fee
            pnl = calc_long_pnl(long_pprice, long_close[1], long_close_qty, inverse, c_mult)
            balance += fee_paid + pnl
            equity = calc_equity(balance, long_psize, long_pprice, shrt_psize, shrt_pprice, prices[k], inverse, c_mult)
            pbr = qty_to_cost(long_psize, long_pprice, inverse, c_mult) / balance
            fills.append((k, timestamps[k], pnl, fee_paid, balance, equity, pbr,
                          long_close_qty, long_close[1], long_psize, long_pprice, long_close_comment))
            next_update_ts = min(next_update_ts, timestamps[k] + latency_simulation_ms)
            if partial_fill:
                long_close = (long_close[0] - long_close_qty, long_close[1], long_close_comment)
            else:
                long_close = (0.0, 0.0, '')
        MAs = new_MAs
    return fills, (True, lowest_eqbal_ratio, closest_bkr)


@njit
def njit_backtest_bancor(ticks: np.ndarray,
                         starting_balance,
                         latency_simulation_ms,
                         maker_fee,
                         qty_step,
                         price_step,
                         min_qty,
                         min_cost,
                         spans,
                         qty_pct,
                         bancor_price_spread,
                         MA_band_spread):
    timestamps = ticks[:, 0]
    qtys = ticks[:, 1]
    prices = ticks[:, 2]

    quot_balance = starting_balance / 2
    coin_balance = quot_balance / ticks[0][2]

    next_update_ts = 0
    fills = []

    bid, ask = (0.0, 0.0, ''), (0.0, 0.0, '')

    prev_k = 0
    # spans are in minutes, convert to sample size
    spans = np.array([span / ((timestamps[1] - timestamps[0]) / (1000 * 60)) for span in spans])

    alphas = 2.0 / (spans + 1.0)
    alphas_ = 1.0 - alphas
    start_idx = int(round(spans.max()))
    MAs = calc_emas_last(prices[:start_idx], spans)
    for k in range(start_idx, len(prices)):
        new_MAs = MAs * alphas_ + prices[k] * alphas
        if qtys[k] == 0.0:
            MAs = new_MAs
            continue

        if timestamps[k] >= next_update_ts:
            # simulate small delay between bot and exchange
            bid, ask = calc_bancor_bid_ask(quot_balance,
                                           coin_balance,
                                           min(MAs),
                                           max(MAs),
                                           prices[k],
                                           prices[k],
                                           qty_step,
                                           price_step,
                                           min_qty,
                                           min_cost,
                                           qty_pct,
                                           bancor_price_spread,
                                           MA_band_spread)
            next_update_ts = timestamps[k] + 5000
        if bid[0] > 0.0 and prices[k] < bid[1]:
            if qtys[k] < bid[0]:
                partial_fill = True
                bid_qty = qtys[k]
                bid_comment = bid[2] + '_partial'
            else:
                partial_fill = False
                bid_qty = bid[0]
                bid_comment = bid[2] + '_full'
            quot_balance -= bid_qty * bid[1]
            fee_paid = -bid_qty * maker_fee
            coin_balance += (bid_qty + fee_paid)
            fills.append((k, timestamps[k], fee_paid, 'coin', bid_qty, bid[1], quot_balance, coin_balance, bid_comment))
            next_update_ts = min(next_update_ts, timestamps[k] + latency_simulation_ms)
            if partial_fill:
                bid = (bid[0] - bid_qty, bid[1], bid_comment)
            else:
                bid = (0.0, 0.0, '')
        if ask[0] < 0.0 and prices[k] > ask[1]:
            if qtys[k] < -ask[0]:
                partial_fill = True
                ask_qty = -qtys[k]
                ask_comment = ask[2] + '_partial'
            else:
                partial_fill = False
                ask_qty = ask[0]
                ask_comment = ask[2] + '_full'
            coin_balance += ask_qty
            cost = qty_to_cost(ask_qty, ask[1], False, 1.0)
            fee_paid = -cost * maker_fee
            quot_balance += cost + fee_paid
            fills.append((k, timestamps[k], fee_paid, 'quot', ask_qty, ask[1], quot_balance, coin_balance, ask_comment))
            next_update_ts = min(next_update_ts, timestamps[k] + latency_simulation_ms)
            if partial_fill:
                ask = (ask[0] - ask_qty, ask[1], ask_comment)
            else:
                ask = (0.0, 0.0, '')

        MAs = new_MAs
    return fills


@njit
def calc_bancor_bid_ask(quot_balance,
                        coin_balance,
                        MA_band_lower,
                        MA_band_upper,
                        highest_bid,
                        lowest_ask,
                        qty_step,
                        price_step,
                        min_qty,
                        min_cost,
                        qty_pct,
                        bancor_price_spread,
                        MA_band_spread) -> ((float, float, str), (float, float, str)):
    bancor_price = quot_balance / coin_balance
    bid_price = round_dn(min([bancor_price * (1 - bancor_price_spread),
                              MA_band_lower * (1 - MA_band_spread),
                              highest_bid]), price_step)
    ask_price = round_up(max([bancor_price * (1 + bancor_price_spread),
                              MA_band_upper * (1 + MA_band_spread),
                              lowest_ask]), price_step)
    min_bid_entry_qty = calc_min_entry_qty(bid_price, False, qty_step, min_qty, min_cost)
    bid_qty = round_dn(min(cost_to_qty(quot_balance, bid_price, False, 1.0),
                           max(coin_balance * 2 * qty_pct, min_bid_entry_qty)), qty_step)
    if bid_qty < min_bid_entry_qty:
        bid_qty = 0.0
    min_ask_entry_qty = calc_min_entry_qty(ask_price, False, qty_step, min_qty, min_cost)
    ask_qty = round_dn(min(coin_balance, max(coin_balance * 2 * qty_pct, min_ask_entry_qty)), qty_step)
    if ask_qty < min_ask_entry_qty:
        ask_qty = 0.0
    return (bid_qty, bid_price, 'bancor_bid'), (-ask_qty, ask_price, 'bancor_ask')





@njit
def calc_bankruptcy_price(balance,
                          long_psize,
                          long_pprice,
                          shrt_psize,
                          shrt_pprice,
                          inverse, c_mult):
    long_pprice = nan_to_0(long_pprice)
    shrt_pprice = nan_to_0(shrt_pprice)
    long_psize *= c_mult
    abs_shrt_psize = abs(shrt_psize) * c_mult
    if inverse:
        shrt_cost = abs_shrt_psize / shrt_pprice if shrt_pprice > 0.0 else 0.0
        long_cost = long_psize / long_pprice if long_pprice > 0.0 else 0.0
        denominator = (shrt_cost - long_cost - balance)
        if denominator == 0.0:
            return 0.0
        bankruptcy_price = (abs_shrt_psize - long_psize) / denominator
    else:
        denominator = long_psize - abs_shrt_psize
        if denominator == 0.0:
            return 0.0
        bankruptcy_price = (-balance + long_psize * long_pprice - abs_shrt_psize * shrt_pprice) / denominator
    return max(0.0, bankruptcy_price)

