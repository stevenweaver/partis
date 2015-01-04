#!/usr/bin/env python

import sys
import os
from subprocess import check_call
import csv

import plotting
has_root = plotting.has_root
if has_root:
    from ROOT import TCanvas, TH1D, TLine, kRed

import utils
import fraction_uncertainty
import paramutils
from hist import Hist
from opener import opener

# ----------------------------------------------------------------------------------------
class MuteFreqer(object):
    def __init__(self, base_outdir, base_plotdir, germline_seqs):
        self.outdir = base_outdir + '/mute-freqs'
        assert base_plotdir != ''
        self.base_plotdir = base_plotdir
        if self.base_plotdir != '':
            self.base_plotdir += '/mute-freqs'
            utils.prep_dir(self.base_plotdir + '/plots', multilings=('*.csv', '*.svg'))
            for region in utils.regions:
                utils.prep_dir(self.base_plotdir + '/' + region + '/plots', multilings=('*.csv', '*.svg'))
                utils.prep_dir(self.base_plotdir + '/' + region + '-per-base/plots', multilings=('*.csv', '*.png'))
        utils.prep_dir(self.outdir, '*.csv')
        self.germline_seqs = germline_seqs
        self.counts = {}
        n_bins, xmin, xmax = 100, 0.0, 1.0
        self.mean_rates = {'all':Hist(n_bins, xmin, xmax)}
        for region in utils.regions:
            self.mean_rates[region] = Hist(n_bins, xmin, xmax)
        
    # ----------------------------------------------------------------------------------------
    def increment(self, info):
        # first do overall mute freqs
        freq = utils.rounded_mutation_rate(self.germline_seqs, info)
        self.mean_rates['all'].fill(freq)
        for region in utils.regions:
            # then do per-region mean mute freqs
            freq = utils.rounded_mutation_rate(self.germline_seqs, info, restrict_to_region=region)
            self.mean_rates[region].fill(freq)

            # then per-gene per-position
            if info[region + '_gene'] not in self.counts:
                self.counts[info[region + '_gene']] = {}
            mute_counts = self.counts[info[region + '_gene']]  # temporary variable to avoid long dict access
            germline_seq = info[region + '_gl_seq']
            query_seq = info[region + '_qr_seq']
            # utils.color_mutants(germline_seq, query_seq, print_result=True, extra_str='  ')
            assert len(germline_seq) == len(query_seq)
            for inuke in range(len(germline_seq)):
                i_germline = inuke + int(info[region + '_5p_del'])  # account for left-side deletions in the indexing
                if i_germline not in mute_counts:  # if we have not yet observed this position in a query sequence, initialize it
                    mute_counts[i_germline] = {'A':0, 'C':0, 'G':0, 'T':0, 'total':0, 'gl_nuke':germline_seq[inuke]}
                mute_counts[i_germline]['total'] += 1
                mute_counts[i_germline][query_seq[inuke]] += 1

    # ----------------------------------------------------------------------------------------
    def write(self, calculate_uncertainty=True, csv_outfname=None):
        cvn = None
        if has_root:
            cvn = TCanvas("cvn", "", 6000, 1000)

        # calculate mute freqs
        n_cached, n_not_cached = 0, 0
        for gene in self.counts:
            mute_counts = self.counts[gene]
            sorted_positions = sorted(mute_counts)
            mute_freqs, plotting_info = {}, []
            for position in sorted_positions:
                mute_freqs[position] = {}
                plotting_info.append({})
                plotting_info[-1]['name'] = utils.sanitize_name(gene) + '_' + str(position)
                plotting_info[-1]['nuke_freqs'] = {}
                n_conserved, n_mutated = 0, 0
                for nuke in utils.nukes:
                    nuke_freq = float(mute_counts[position][nuke]) / mute_counts[position]['total']
                    mute_freqs[position][nuke] = nuke_freq
                    plotting_info[-1]['nuke_freqs'][nuke] = nuke_freq
                    if calculate_uncertainty:  # it's kinda slow
                        errs = fraction_uncertainty.err(mute_counts[position][nuke], mute_counts[position]['total'])
                        if errs[2]:
                            n_cached += 1
                        else:
                            n_not_cached += 1
                        # print nuke_freq, errs[0], errs[1], '(', mute_counts[position][nuke], ',', mute_counts[position]['total'], ')'
                        assert errs[0] <= nuke_freq  # these checks are probably unnecessary. EDIT and totally saved my ass about ten minutes after writing the previous statement
                        assert nuke_freq <= errs[1]
                        mute_freqs[position][nuke + '_lo_err'] = errs[0]
                        mute_freqs[position][nuke + '_hi_err'] = errs[1]

                    if nuke == mute_counts[position]['gl_nuke']:
                        n_conserved += mute_counts[position][nuke]
                    else:
                        n_mutated += mute_counts[position][nuke]  # sum over A,C,G,T
                    # uncert = fraction_uncertainty.err(obs, total)  # uncertainty for each nuke
                mute_counts[position]['freq'] = float(n_mutated) / mute_counts[position]['total']
                mutated_fraction_err = (0.0, 0.0)
                if calculate_uncertainty:  # it's kinda slow
                    mutated_fraction_err = fraction_uncertainty.err(n_mutated, mute_counts[position]['total'])
                    if mutated_fraction_err[2]:
                        n_cached += 1
                    else:
                        n_not_cached += 1
                mute_counts[position]['freq_lo_err'] = mutated_fraction_err[0]
                mute_counts[position]['freq_hi_err'] = mutated_fraction_err[1]

            # write to csv
            outfname = self.outdir + '/' + utils.sanitize_name(gene) + '.csv'
            with opener('w')(outfname) as outfile:
                nuke_header = []
                for nuke in utils.nukes:
                    nuke_header.append(nuke)
                    nuke_header.append(nuke + '_lo_err')
                    nuke_header.append(nuke + '_hi_err')
                writer = csv.DictWriter(outfile, ('position', 'mute_freq', 'lo_err', 'hi_err') + tuple(nuke_header))
                writer.writeheader()
                for position in sorted_positions:
                    row = {'position':position,
                           'mute_freq':mute_counts[position]['freq'],
                           'lo_err':mute_counts[position]['freq_lo_err'],
                           'hi_err':mute_counts[position]['freq_hi_err']}
                    for nuke in utils.nukes:
                        row[nuke] = mute_freqs[position][nuke]
                        row[nuke + '_lo_err'] = mute_freqs[position][nuke + '_lo_err']
                        row[nuke + '_hi_err'] = mute_freqs[position][nuke + '_hi_err']
                    writer.writerow(row)
                
            if has_root: # make a plot
                paramutils.make_mutefreq_plot(self.base_plotdir + '/' + utils.get_region(gene) + '-per-base', utils.sanitize_name(gene), plotting_info)

                hist = TH1D('hist_' + utils.sanitize_name(gene), '',
                            sorted_positions[-1] - sorted_positions[0] + 1,
                            sorted_positions[0] - 0.5, sorted_positions[-1] + 0.5)
                lo_err_hist = TH1D(hist)
                hi_err_hist = TH1D(hist)
                for position in sorted_positions:
                    hist.SetBinContent(hist.FindBin(position), mute_counts[position]['freq'])
                    lo_err_hist.SetBinContent(hist.FindBin(position), mute_counts[position]['freq_lo_err'])
                    hi_err_hist.SetBinContent(hist.FindBin(position), mute_counts[position]['freq_hi_err'])
                hframe = TH1D(hist)
                hframe.SetTitle(gene + ';;')
                hframe.Reset()
                hframe.SetMinimum(lo_err_hist.GetMinimum() - 0.03)
                hframe.SetMaximum(1.1*hi_err_hist.GetMaximum())
                hframe.Draw('')
                line = TLine(hist.GetXaxis().GetXmin(), 0., hist.GetXaxis().GetXmax(), 0.)
                line.SetLineColor(0)
                line.Draw()  # can't figure out how to convince hframe not to draw a horizontal line at y=0, so... cover it up
                hist.SetLineColor(419)
                hist.SetLineWidth(2)
                hist.Draw('same')
                lo_err_hist.SetLineColor(kRed+2)
                hi_err_hist.SetLineColor(kRed+2)
                lo_err_hist.SetMarkerColor(kRed+2)
                hi_err_hist.SetMarkerColor(kRed+2)
                lo_err_hist.SetMarkerStyle(22)
                hi_err_hist.SetMarkerStyle(23)
                lo_err_hist.SetMarkerSize(1)
                hi_err_hist.SetMarkerSize(1)
                lo_err_hist.Draw('p same')
                hi_err_hist.Draw('p same')
                if self.base_plotdir != '':
                    plotfname = self.base_plotdir + '/' + utils.get_region(gene) + '/plots/' + utils.sanitize_name(gene) + '.svg'
                    cvn.SaveAs(plotfname)

        if has_root:
            # make mean mute freq hists
            self.mean_rates['all'].normalize()
            self.mean_rates['all'].write(csv_outfname.replace('REGION', 'all'))  # hackey hackey hackey replacement... *sigh*
            hist = plotting.make_hist_from_bin_entry_file(csv_outfname.replace('REGION', 'all'), 'all-mean-freq')
            plotting.draw(hist, 'float', plotname='all-mean-freq', plotdir=self.base_plotdir, stats='mean', bounds=(0.0, 0.4), write_csv=True)
            for region in utils.regions:
                self.mean_rates[region].normalize()
                self.mean_rates[region].write(csv_outfname.replace('REGION', region))
                hist = plotting.make_hist_from_bin_entry_file(csv_outfname.replace('REGION', region), region+'-mean-freq')
                plotting.draw(hist, 'float', plotname=region+'-mean-freq', plotdir=self.base_plotdir, stats='mean', bounds=(0.0, 0.4), write_csv=True)
            check_call(['./makeHtml', self.base_plotdir, '3', 'null', 'svg'])

            # then write make html file and fix permissiions
            if self.base_plotdir != '':
                for region in utils.regions:
                    check_call(['./makeHtml', self.base_plotdir + '/' + region, '1', 'null', 'svg'])
                    check_call(['./makeHtml', self.base_plotdir + '/' + region + '-per-base', '1', 'null', 'png'])
                check_call(['./permissify-www', self.base_plotdir])  # NOTE this should really permissify starting a few directories higher up
        return (n_cached, n_not_cached)

    # ----------------------------------------------------------------------------------------
    def clean(self):
        """ remove all the parameter files """
        for gene in self.counts:
            outfname = self.outdir + '/' + utils.sanitize_name(gene) + '.csv'
            os.remove(outfname)
        os.rmdir(self.outdir)
