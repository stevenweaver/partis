import os
import sys
import math
import csv

import utils
from opener import opener

# ----------------------------------------------------------------------------------------
class ClusterPath(object):
    def __init__(self, initial_path_index=0):
        self.initial_path_index = initial_path_index  # NOTE this is set to None if it's nonsensical, e.g. if we're merging several paths with different indices

        # NOTE make *damn* sure if you add another list here that you also take care of it in remove_first_partition()
        self.partitions = []  # it would of course be damn nice to glomph these into a class at some point
        self.logprobs = []
        self.n_procs = []
        self.adj_mis = []
        self.ccfs = []  # pair of floats (not just a float) for each partition
        self.logweights = []
        self.n_lists = 6  # just to make sure you don't forget

        self.best_minus = 30.  # rewind by this many units of log likelihood when merging separate processes (note that this should really depend on the number of sequences)
        self.i_best, self.i_best_minus_x = None, None
        self.we_have_an_adj_mi = False  # did we read in at least one adj mi value from a file?

    # ----------------------------------------------------------------------------------------
    def update_best_minus_x_partition(self):
        if math.isinf(self.logprobs[self.i_best]):  # if logprob is infinite, set best and best minus x to the latest one
            self.i_best_minus_x = self.i_best
            return
        for ip in range(len(self.partitions)):  # they should be in order of increasing logprob (at least within a give number of procs)
            if self.n_procs[ip] != self.n_procs[self.i_best]:  # only consider partitions with the same number of procs (e.g. if best partition is for 1 proc, we want the best-minus-x to also be for 1 proc)
                continue
            if self.logprobs[ip] > self.logprobs[self.i_best] - self.best_minus:  # pick the first one that is above threshold
                self.i_best_minus_x = ip
                break

    # ----------------------------------------------------------------------------------------
    def add_partition(self, partition, logprob, n_procs, logweight=None, adj_mi=None, ccfs=[None, None]):
        # NOTE you typically want to allow duplicate (in terms of log prob) partitions, since they can have different n procs
        self.partitions.append(partition)
        self.logprobs.append(logprob)
        self.n_procs.append(n_procs)
        self.logweights.append(logweight)
        self.adj_mis.append(adj_mi)
        if len(ccfs) != 2:
            raise Exception('tried to add partition with ccfs of length %d (%s)' % (len(ccfs), ccfs))
        self.ccfs.append(ccfs)
        # set this as the best partition if 1) we haven't set i_best yet 2) this partition is more likely than i_best 3) i_best is set for a larger number of procs or 4) logprob is infinite (i.e. it's probably point/vsearch partis)
        # NOTE we always treat the most recent partition with infinite logprob as the best
        if self.i_best is None or logprob > self.logprobs[self.i_best] or n_procs < self.n_procs[self.i_best] or math.isinf(logprob):
            self.i_best = len(self.partitions) - 1
        self.update_best_minus_x_partition()

    # ----------------------------------------------------------------------------------------
    def remove_first_partition(self):
        # NOTE after you do this, none of the 'best' shit is any good any more
        # NOTE also that this is only used for smc
        self.partitions.pop(0)
        self.logprobs.pop(0)
        self.n_procs.pop(0)
        self.adj_mis.pop(0)
        self.ccfs.pop(0)
        self.logweights.pop(0)
        assert self.n_lists == 6  # make sure we didn't add another list and forget to put it in here

    # ----------------------------------------------------------------------------------------
    def readfile(self, fname):
        with opener('r')(fname) as infile:
            reader = csv.DictReader(infile)
            lines = [line for line in reader]
            self.readlines(lines)

    # ----------------------------------------------------------------------------------------
    def readlines(self, lines):
        for line in lines:
            if 'path_index' in line and int(line['path_index']) != self.initial_path_index:  # if <lines> contains more than one path_index, that means they represent more than one path, so you need to use glomerator, not just one ClusterPath
                raise Exception('path index in lines %d doesn\'t match my initial path index %d' % (int(line['path_index']), self.initial_path_index))
            partitionstr = line['partition'] if 'partition' in line else line['clusters']  # backwards compatibility -- used to be 'clusters' and there's still a few old files floating around
            partition = [cluster_str.split(':') for cluster_str in partitionstr.split(';')]
            adj_mi = None
            if 'adj_mi' in line and line['adj_mi'] != '' and float(line['adj_mi']) != -1.:
                adj_mi = float(line['adj_mi'])
                self.we_have_an_adj_mi = True
            ccfs = [None, None]
            if 'ccf_under' in line and 'ccf_over' in line and line['ccf_under'] != '' and line['ccf_over'] != '':
                ccfs = [float(line['ccf_under']), float(line['ccf_over'])]
            self.add_partition(partition, float(line['logprob']), int(line.get('n_procs', 1)), logweight=float(line.get('logweight', 0)), adj_mi=adj_mi, ccfs=ccfs)

    # ----------------------------------------------------------------------------------------
    def calculate_missing_values(self, reco_info, only_ip=None):
        for ip in range(len(self.partitions)):
            if only_ip is not None and ip != only_ip:
                continue

            if self.adj_mis[ip] is not None:  # already have it/them
                assert self.ccfs[ip][0] is not None and self.ccfs[ip][1] is not None
                continue

            true_partition = utils.get_true_partition(reco_info, ids=[uid for cluster in self.partitions[ip] for uid in cluster])
            self.adj_mis[ip] = utils.adjusted_mutual_information(self.partitions[ip], true_partition)
            assert self.ccfs[ip] == [None, None]
            self.ccfs[ip] = utils.correct_cluster_fractions(self.partitions[ip], reco_info)
            self.we_have_an_adj_mi = True

    # ----------------------------------------------------------------------------------------
    def get_adj_mi_str(self, ip):
        adj_mi_str = ''
        if self.we_have_an_adj_mi:
            if self.adj_mis[ip] is None:
                adj_mi_str = '   -    '
            else:
                if self.adj_mis[ip] > 1e-3:
                    adj_mi_str = '%-5.3f' % self.adj_mis[ip]
                else:
                    adj_mi_str = '%-5.0e' % self.adj_mis[ip]

        return '     %5s   ' % (adj_mi_str)

    # ----------------------------------------------------------------------------------------
    def get_ccf_str(self, ip):
        ccf_str = ''
        if self.we_have_an_adj_mi:
            if self.ccfs[ip] == [None, None]:  # NOTE if you set a ccf with a tuple instead of a list this'll fail. So don't do that.
                ccf_str = '   -  -    '
            else:
                ccf_str = ' %5.2f %5.2f    ' % tuple(self.ccfs[ip])

        return ccf_str

    # ----------------------------------------------------------------------------------------
    def print_partition(self, ip, reco_info=None, extrastr='', abbreviate=True, smc_print=False):
        if ip > 0:  # delta between this logprob and the previous one
            delta_str = '%.1f' % (self.logprobs[ip] - self.logprobs[ip-1])
        else:
            delta_str = ''
        print '      %s  %-12.2f%-7s   %-5d  %4d' % (extrastr, self.logprobs[ip], delta_str, len(self.partitions[ip]), self.n_procs[ip]),

        # logweight (and inverse of number of potential parents)
        if self.logweights[ip] is not None and smc_print:
            way_str, logweight_str = '', ''
            expon = math.exp(self.logweights[ip])
            n_ways = 0 if expon == 0. else 1. / expon
            way_str = ('%.1f' % n_ways) if n_ways < 1e7 else ('%8.1e' % n_ways)
            logweight_str = '%8.3f' % self.logweights[ip]

        print self.get_adj_mi_str(ip),
        print self.get_ccf_str(ip),

        if self.logweights[ip] is not None and smc_print:
            print '   %10s    %8s   ' % (way_str, logweight_str),

        # clusters
        for cluster in self.partitions[ip]:
            if abbreviate:
                cluster_str = ':'.join(['o' for uid in cluster])
            else:
                cluster_str = ':'.join(sorted([str(uid) for uid in cluster]))

            if reco_info is not None and not utils.from_same_event(reco_info, cluster):
                cluster_str = utils.color('red', cluster_str)
            
            if abbreviate:
                print ' %s' % cluster_str,
            else:
                print '   %s' % cluster_str,
        print ''

    # ----------------------------------------------------------------------------------------
    def print_partitions(self, reco_info=None, extrastr='', abbreviate=True, print_header=True, n_to_print=None, smc_print=False, calc_missing_values='none'):
        assert calc_missing_values in ['none', 'all', 'best']
        if reco_info is not None and calc_missing_values == 'all':
            self.calculate_missing_values(reco_info)

        if print_header:
            print '    %7s %10s   %-7s %5s  %4s' % ('', 'logprob', 'delta', 'clusters', 'n_procs'),
            if reco_info is not None or self.we_have_an_adj_mi:
                print ' %5s' % ('adj mi'),
                print ' %5s %5s' % ('ccf under', 'over'),
            if self.logweights[0] is not None and smc_print:
                print '  %10s  %7s' % ('pot.parents', 'logweight'),
            print ''

        for ip in self.get_surrounding_partitions(n_partitions=n_to_print):
            if reco_info is not None and calc_missing_values == 'best' and ip == self.i_best:
                self.calculate_missing_values(reco_info, only_ip=ip)
            mark = '      '
            if ip == self.i_best:
                mark = 'best  '
            if ip == self.i_best_minus_x:
                mark = mark[:-2] + '* '
            if mark.count(' ') < len(mark):
                mark = utils.color('yellow', mark)
            self.print_partition(ip, reco_info, extrastr=mark+extrastr, abbreviate=abbreviate, smc_print=smc_print)

    # ----------------------------------------------------------------------------------------
    def get_surrounding_partitions(self, n_partitions):
        """ return a list of partition indices centered on <self.i_best> of length <n_partitions> """
        if n_partitions is None:  # print all partitions
            ilist = range(len(self.partitions))
        else:  # print the specified number surrounding the maximum logprob
            if n_partitions < 0 or n_partitions >= len(self.partitions):
                n_partitions = len(self.partitions)
            ilist = [self.i_best, ]
            while len(ilist) < n_partitions:  # add partition numbers before and after <i_best> until we get to <n_partitions>
                if ilist[0] > 0:  # stop adding them beforehand if we've hit the first partition
                    ilist.insert(0, ilist[0] - 1)
                if len(ilist) < n_partitions and ilist[-1] < len(self.partitions) - 1:  # don't add them afterward if we already have enough, or if we're already at the end
                    ilist.append(ilist[-1] + 1)

        return ilist

    # ----------------------------------------------------------------------------------------
    def get_parent_clusters(self, ipart):
        """ Return the parent clusters that were merged to form the <ipart>th partition. """
        if ipart == 0:
            raise Exception('get_parent_clusters got ipart of zero... that don\'t make no sense yo')
        if len(self.partitions[ipart - 1]) <= len(self.partitions[ipart]):
            return None  # this step isn't a merging step -- it's a synthetic rewinding step due to multiple processes

        parents = []
        for cluster in self.partitions[ipart - 1]:  # find all clusters in the previous partition that aren't in the current one
            if cluster not in self.partitions[ipart]:
                parents.append(cluster)
        assert len(parents) == 2  # there should've been two -- those're the two that were merged to form the new cluster
        return parents

    # ----------------------------------------------------------------------------------------
    def set_synthetic_logweight_history(self, reco_info):
        # TODO switch clusterpath.cc back to using these
        def potential_n_parents(partition):
            combifactor = 0
            for cluster in partition:
                n_k = len(cluster)
                combifactor += pow(2, n_k - 1) - 1
            if combifactor == 0:
                combifactor = 1
            return combifactor

        for ip in range(len(self.partitions)):
            if ip == 0:
                last_logweight = 0.
            else:
                last_logweight = self.logweights[ip-1]
            this_logweight = last_logweight + math.log(1. / potential_n_parents(self.partitions[ip]))
            self.logweights[ip] = this_logweight

    # ----------------------------------------------------------------------------------------
    def write_partitions(self, writer, headers, reco_info, true_partition, path_index=None, n_to_write=None, calc_missing_values='none'):

        # ----------------------------------------------------------------------------------------
        def get_bad_clusters(part):
            bad_clusters = []  # inferred clusters that aren't really all from the same event
            for ic in range(len(part)):
                same_event = utils.from_same_event(reco_info, part[ic])  # are all the sequences from the same event?
                entire_cluster = True  # ... and if so, are they the entire true cluster?
                if same_event:
                    reco_id = reco_info[part[ic][0]]['reco_id']  # they've all got the same reco_id then, so pick an aribtrary one
                    true_cluster = true_partition[reco_id]
                    for uid in true_cluster:
                        if uid not in part[ic]:
                            entire_cluster = False
                            break
                else:
                    entire_cluster = False
                if not same_event or not entire_cluster:
                    bad_clusters.append(':'.join(part[ic]))

            if len(bad_clusters) > 25:
                bad_clusters = ['too', 'long']

            return bad_clusters

        assert calc_missing_values in ['none', 'all', 'best']
        if reco_info is not None and calc_missing_values == 'all':
            self.calculate_missing_values(reco_info)

        # ----------------------------------------------------------------------------------------
        for ipart in self.get_surrounding_partitions(n_partitions=n_to_write):
            part = self.partitions[ipart]
            cluster_str = ''
            for ic in range(len(part)):
                if ic > 0:
                    cluster_str += ';'
                cluster_str += ':'.join(part[ic])

            row = {'logprob' : self.logprobs[ipart],
                   'n_clusters' : len(part),
                   'n_procs' : self.n_procs[ipart],
                   'partition' : cluster_str}
            if 'adj_mi' in headers:
                if reco_info is not None and calc_missing_values == 'best' and ipart == self.i_best:
                    self.calculate_missing_values(reco_info, only_ip=ipart)
                if self.adj_mis[ipart] is not None:  # we already calculated it
                    row['adj_mi'] = self.adj_mis[ipart]
                    row['ccf_under'], row['ccf_over'] = self.ccfs[ipart]  # for now assume we calculated the ccfs if we did adj mi
            if 'n_true_clusters' in headers:
                row['n_true_clusters'] = len(true_partition)
            if 'bad_clusters' in headers:
                row['bad_clusters'] = ';'.join(get_bad_clusters(part))
            if 'path_index' in headers:
                row['path_index'] = path_index
                row['logweight'] = self.logweights[ipart]

            writer.writerow(row)
