import os
import glob
import sys
import numpy
import random
from collections import OrderedDict
import time
import csv
from subprocess import check_call, Popen, check_output, PIPE
import itertools
sys.path.insert(1, './python')
csv.field_size_limit(sys.maxsize)
from hist import Hist
import seqfileopener
import utils
import baseutils
# from clusterplot import ClusterPlot
from clusterpath import ClusterPath
import plotting

changeorandomcrapstr = '_db-pass_parse-select_clone-pass.tab'

# ----------------------------------------------------------------------------------------
def get_title(args, label, n_leaves, mut_mult):
    if args.data:
        title = 'data (%s %s)' % (args.dataset, label)
    else:
        title = '%d leaves, %dx mutation' % (n_leaves, mut_mult)
        if args.indels:
            title += ', indels'
    return title

# ----------------------------------------------------------------------------------------
def leafmutstr(args, n_leaves, mut_mult):
    return_str = 'simu-' + str(n_leaves) + '-leaves-' + str(mut_mult) + '-mutate'
    if args.indels:
        return_str += '-indels'
    if args.lonely_leaves:
        return_str += '-lonely-leaves'
    return return_str

# ----------------------------------------------------------------------------------------
def get_outdirname(args, label, no_subset=False):
    outdirname = args.fsdir + '/' + label
    if not no_subset:
        if args.subset is not None:
            outdirname += '/subset-' + str(args.subset)
        if args.istartstop is not None:
            outdirname += '/istartstop-' + '-'.join([str(i) for i in args.istartstop])
    return outdirname

# ----------------------------------------------------------------------------------------
def get_simfname(args, label, n_leaves, mut_mult, no_subset=False):
    return get_outdirname(args, label, no_subset=no_subset) + '/' + leafmutstr(args, n_leaves, mut_mult) + '.csv'

# ----------------------------------------------------------------------------------------
def get_program_workdir(args, program_name, label, n_leaves, mut_mult):
    basedir = '/fh/fast/matsen_e/dralph/work/' + program_name + '/' + label
    if args.data:
        outdir = basedir + '/data'
    else:
        outdir = basedir + '/' + leafmutstr(args, n_leaves, mut_mult)
    if args.subset is not None:
        outdir += '/subset-' + str(args.subset)
    if args.istartstop is not None:
        outdir += '/istartstop-' + '-'.join([str(i) for i in args.istartstop])
    return outdir

# ----------------------------------------------------------------------------------------
def get_changeo_outdir(args, label, n_leaves, mut_mult):
    if args.bak:
        changeo_fsdir = '/fh/fast/matsen_e/dralph/work/changeo.bak/' + label
    else:
        changeo_fsdir = '/fh/fast/matsen_e/dralph/work/changeo/' + label
    if args.data:
        imgtdir = changeo_fsdir + '/data'
    else:
        imgtdir = changeo_fsdir + '/' + leafmutstr(args, n_leaves, mut_mult).replace('-', '_')
    return imgtdir

# ----------------------------------------------------------------------------------------
def generate_incorrect_partition(true_partition, n_misassigned, error_type, debug=False):
    new_partition = list(true_partition)
    if debug:
        print '  before', new_partition
    for _ in range(n_misassigned):
        iclust = random.randint(0, len(new_partition) - 1)  # choose a cluster from which to remove a sequence
        iseq = random.randint(0, len(new_partition[iclust]) - 1)  # and choose the sequence to remove from this cluster
        uid = new_partition[iclust][iseq]
        new_partition[iclust].remove(uid)  # remove it
        if [] in new_partition:
            new_partition.remove([])
        if error_type == 'singletons':  # put the sequence in a cluster by itself
            new_partition.append([uid, ])
            if debug:
                print '    %s: %d --> singleton' % (uid, iclust)
        elif error_type == 'reassign':  # choose a different cluster to add it to
            inewclust = iclust
            while inewclust == iclust:
                inewclust = random.randint(0, len(new_partition) - 1)
            new_partition[inewclust].append(uid)
            if debug:
                print '    %s: %d --> %d' % (uid, iclust, inewclust)
        else:
            raise Exception('%s not among %s' % (error_type, 'singletons, reassign'))
    if debug:
        print '  after', new_partition
    return new_partition

# ----------------------------------------------------------------------------------------
def parse_vollmers(args, these_hists, these_adj_mis, these_ccfs, these_partitions, seqfname, outdir, reco_info, rebin=None):
    vollmers_fname = seqfname.replace('.csv', '-run-viterbi.csv')
    n_lines = 0
    with open(vollmers_fname) as vfile:
        vreader = csv.DictReader(vfile)
        for line in vreader:
            n_lines += 1
            partitionstr = line['partition'] if 'partition' in line else line['clusters']  # backwards compatibility -- used to be 'clusters' and there's still a few old files floating around
            partition = utils.get_partition_from_str(partitionstr)
            these_partitions['vollmers-' + line['threshold']] = partition
            vhist = plotting.get_cluster_size_hist(partition, rebin=rebin)
            histfname = outdir + '/hists/vollmers-'  + line['threshold'] + '.csv'
            vhist.write(histfname)
            these_hists['vollmers-' + line['threshold']] = vhist
            if not args.data:
                these_adj_mis['vollmers-' + line['threshold']] = float(line['adj_mi'])
                print '    %s: %f' % ('vollmers-' + line['threshold'], float(line['adj_mi']))
                write_float_val(outdir + '/adj_mi/' + os.path.basename(histfname), float(line['adj_mi']), 'adj_mi')

                vollmers_clusters = [cl.split(':') for cl in partitionstr.split(';')]
                true_partition = utils.get_true_partition(reco_info)
                print 'not checking intersection!'
                # utils.check_intersection_and_complement(vollmers_clusters, true_partition)
                truehist = plotting.get_cluster_size_hist(true_partition, rebin=rebin)
                these_partitions['true'] = true_partition
                truehist.write(outdir + '/hists/true.csv')  # will overwite itself a few times
                these_hists['true'] = truehist

                ccfs = utils.correct_cluster_fractions(vollmers_clusters, reco_info)
                these_ccfs['vollmers-' + line['threshold']] = ccfs
                print '    %s: %.2f %.2f' % ('vollmers-' + line['threshold'], ccfs[0], ccfs[1])
                write_float_val(outdir + '/ccf_under/' + os.path.basename(histfname), ccfs[0], 'ccf_under')
                write_float_val(outdir + '/ccf_over/' + os.path.basename(histfname), ccfs[1], 'ccf_over')
    if n_lines < 1:
        raise Exception('zero partition lines read from %s' % vollmers_fname)

# ----------------------------------------------------------------------------------------
def parse_changeo(args, label, n_leaves, mut_mult, these_hists, these_adj_mis, these_ccfs, these_partitions, simfbase, outdir, rebin=None):
    indir = get_changeo_outdir(args, label, n_leaves, mut_mult)  #fsdir.replace('/partis-dev/_output', '/changeo')
    if args.data:
        fbase = 'data'
    else:
        fbase = simfbase.replace('-', '_')
    if args.bak:
        infname = indir + '/' + fbase + changeorandomcrapstr
    else:
        # infname = indir + '/' + fbase + '/' + changeorandomcrapstr
        infname = indir + '/' + changeorandomcrapstr
    if args.subset is not None:
        infname = infname.replace(changeorandomcrapstr, 'subset-' + str(args.subset) + changeorandomcrapstr)
    if args.istartstop is not None:  # TODO not yet functional
        infname = infname.replace(changeorandomcrapstr, 'istartstop_' + '_'.join([str(i) for i in args.istartstop]) + changeorandomcrapstr)

    id_clusters = {}  # map from cluster id to list of seq ids
    with open(infname) as chfile:
        reader = csv.DictReader(chfile, delimiter='\t')
        for line in reader:
            clid = line['CLONE']
            uid = line['SEQUENCE_ID']
            if clid not in id_clusters:
                id_clusters[clid] = []
            id_clusters[clid].append(uid)

    partition = [ids for ids in id_clusters.values()]
    these_hists['changeo'] = plotting.get_cluster_size_hist(partition, rebin=rebin)
    these_hists['changeo'].write(outdir + '/hists/changeo.csv')
    these_partitions['changeo'] = partition
    if not args.data:
        adj_mi_fname = infname.replace(changeorandomcrapstr, '-adj_mi.csv')
        check_call(['cp', adj_mi_fname, outdir + '/adj_mi/changeo.csv'])
        these_adj_mis['changeo'] = read_float_val(adj_mi_fname, 'adj_mi')
        print '    %s: %f' % ('changeo', these_adj_mis['changeo'])

        ccfs = []
        for etype in ['under', 'over']:
            ccf_fname = infname.replace(changeorandomcrapstr, '-ccf_' + etype+ '.csv')
            check_call(['cp', ccf_fname, outdir + '/ccf_' + etype + '/changeo.csv'])
            ccfs.append(read_float_val(ccf_fname, 'ccf_' + etype))

        these_ccfs['changeo'] = ccfs
        print '    %s: %.2f %.2f' % ('changeo', these_ccfs['changeo'][0], these_ccfs['changeo'][1])

# ----------------------------------------------------------------------------------------
def parse_mixcr(args, these_hists, these_adj_mis, these_ccfs, seqfname, outdir):
    mixfname = seqfname.replace('.csv', '-mixcr.tsv')
    cluster_size_list = []  # put 'em in a list first so we know where to put the hist limits
    max_cluster_size = 1
    with open(mixfname) as mixfile:
        reader = csv.DictReader(mixfile, delimiter='\t')
        for line in reader:
            csize = int(line['Clone count'])
            cluster_size_list.append(csize)
            if csize > max_cluster_size:
                max_cluster_size = csize
    mixhist = Hist(max_cluster_size, 0.5, max_cluster_size + 0.5)
    for csize in cluster_size_list:
        mixhist.fill(csize)
    these_hists['mixcr'] = mixhist
    mixhist.write(outdir + '/hists/mixcr.csv')
    if not args.data:
        these_adj_mis['mixcr'] = -1.
        these_ccfs['mixcr'] = -1., -1.
        write_float_val(outdir + '/adj_mi/mixcr.csv', -1., 'adj_mi')
        write_float_val(outdir + '/ccf_under/mixcr.csv', -1., 'ccf_under')
        write_float_val(outdir + '/ccf_over/mixcr.csv', -1., 'ccf_over')

# ----------------------------------------------------------------------------------------
def parse_partis(args, action, these_hists, these_adj_mis, these_ccfs, these_partitions, seqfname, outdir, reco_info, rebin=None):
    cpath = ClusterPath()
    cpath.readfile(seqfname.replace('.csv', '-' + action + '.csv'))
    hist = plotting.get_cluster_size_hist(cpath.partitions[cpath.i_best], rebin=rebin)
    these_partitions[action + ' partis'] = cpath.partitions[cpath.i_best]
    hist.write(outdir + '/hists/' + action + '.csv')
    these_hists[action + ' partis'] = hist
    if not args.data:
        these_adj_mis[action + ' partis'] = cpath.adj_mis[cpath.i_best]
        print '    %s: %f' % (action + ' partis', cpath.adj_mis[cpath.i_best])
        write_float_val(outdir + '/adj_mi/' + action + '.csv', cpath.adj_mis[cpath.i_best], 'adj_mi')

        ccfs = utils.correct_cluster_fractions(cpath.partitions[cpath.i_best], reco_info)
        these_ccfs[action + ' partis'] = ccfs
        write_float_val(outdir + '/ccf_under/' + action + '.csv', ccfs[0], 'ccf_under')
        write_float_val(outdir + '/ccf_over/' + action + '.csv', ccfs[1], 'ccf_over')

# ----------------------------------------------------------------------------------------
def write_float_val(fname, val, valname):
    if not os.path.exists(os.path.dirname(fname)):
        os.makedirs(os.path.dirname(fname))
    with open(fname, 'w') as outfile:
        writer = csv.DictWriter(outfile, [valname])
        writer.writerow({valname : val})

# ----------------------------------------------------------------------------------------
def read_float_val(fname, valname):
    """ read file with a single number """
    with open(fname) as infile:
        reader = csv.DictReader(infile, fieldnames=[valname])
        for line in reader:
            return float(line[valname])
    raise Exception('something wrong with %s file' % fname)

# ----------------------------------------------------------------------------------------
def make_a_distance_plot(args, metric, combinations, reco_info, cachevals, plotdir, plotname, plottitle):
    def get_joint_key(k1, k2):
        """ figure out which order we have <k1>, <k2> in the cache (if neither, return None) """
        jk1 = k1 + ':' + k2
        jk2 = k2 + ':' + k1
        if jk1 in cachevals:
            return jk1
        elif jk2 in cachevals:
            return jk2
        else:
            return None

    if metric == 'logprob':
        nbins, xmin, xmax = 40, -55, 60
        xlabel = 'log likelihood ratio'
    elif metric == 'naive_hfrac':
        if args.zoom:
            nbins, xmin, xmax = 30, 0., 0.2
        else:
            nbins, xmin, xmax = 70, 0., 0.65
        xlabel = 'naive hamming fraction'
    hists = OrderedDict()
    hists['nearest-clones'], hists['farthest-clones'], hists['all-clones'], hists['not'] = [Hist(nbins, xmin, xmax) for _ in range(4)]
    bigvals, smallvals = {}, {}
    for key_a, key_b in combinations:  # <key_[ab]> is colon-separated string (not a list of keys)
        a_ids, b_ids = key_a.split(':'), key_b.split(':')
        if not utils.from_same_event(reco_info, a_ids) or not utils.from_same_event(reco_info, b_ids):  # skip clusters that were erroneously merged -- i.e., in effect, assume the previous step didn't screw up at all
            raise Exception('woop')
        jk = get_joint_key(key_a, key_b)
        if jk is None:  # if we don't have the joint logprob cached
            continue

        if metric == 'logprob':
            # jk = get_joint_key(key_a, key_b)
            # if jk is None:  # if we don't have the joint logprob cached
            #     continue
            lratio = cachevals[jk] - cachevals[key_a] - cachevals[key_b]
            # print '%f - %f - %f = %f' % (cachevals[jk], cachevals[key_a], cachevals[key_b], lratio),
            mval = lratio
        elif metric == 'naive_hfrac':
            # mval = utils.hamming_fraction(cachevals[key_a], cachevals[key_b])
            mval = cachevals[jk]
        else:
            assert False

        if utils.from_same_event(reco_info, a_ids + b_ids):
            hists['all-clones'].fill(mval)
            for key in (key_a, key_b):
                if key not in bigvals:
                    bigvals[key] = mval
                if mval > bigvals[key]:
                    bigvals[key] = mval
                if key not in smallvals:
                    smallvals[key] = mval
                if mval < smallvals[key]:
                    smallvals[key] = mval
        else:
            hists['not'].fill(mval)

    if metric == 'logprob':
        bigkey = 'nearest'  # i.e. for logprob ratio, big values mean sequences are nearby
        smallkey = 'farthest'
    elif metric == 'naive_hfrac':
        bigkey = 'farthest'
        smallkey = 'nearest'
    for val in bigvals.values():
        hists[bigkey + '-clones'].fill(val)
    for val in smallvals.values():
        hists[smallkey + '-clones'].fill(val)

    fig, ax = plotting.mpl_init()
    ignore = False
    if not args.dont_normalize:
        for k, h in hists.items():
            h.normalize(include_overflows=not ignore, expect_empty=True)
            # print '    %20s %f' % (k, h.get_mean(ignore_overflows=ignore))  # NOTE ignoring overflows is kind of silly here!
    plots = {}
    plots['clonal'] = hists['all-clones'].mpl_plot(ax, ignore_overflows=ignore, label='clonal', alpha=0.7, linewidth=6)
    plots['not'] = hists['not'].mpl_plot(ax, ignore_overflows=ignore, label='non-clonal', linewidth=4)  #linewidth=7, alpha=0.5)
    # plots['nearest'] = hists['nearest-clones'].mpl_plot(ax, ignore_overflows=ignore, label='nearest clones', linewidth=3)
    # plots['farthest'] = hists['farthest-clones'].mpl_plot(ax, ignore_overflows=ignore, label='farthest clones', linewidth=3, linestyle='--')
    if args.logaxis:
        ax.set_yscale('log')
    delta = xmax - xmin
    leg_loc = None
    if metric == 'naive_hfrac':
        leg_loc = (0.5, 0.6)
    plotting.mpl_finish(ax, plotdir, plotname, title=plottitle, xlabel=xlabel, ylabel='frequency' if not args.dont_normalize else 'counts', xbounds=[xmin - 0.03*delta, xmax + 0.03*delta], leg_loc=leg_loc)

# ----------------------------------------------------------------------------------------
def make_distance_plots(args, label, n_leaves, mut_mult, cachefname, reco_info, metric):
    cachevals = {}
    singletons, pairs, triplets, quads = [], [], [], []
    with open(cachefname) as cachefile:
        reader = csv.DictReader(cachefile)
        # iline = 0
        for line in reader:
            if metric == 'logprob':
                if line[metric] == '':
                    continue
                cachevals[line['unique_ids']] = float(line['logprob'])
            elif metric == 'naive_hfrac':
                cachevals[line['unique_ids']] = -1. if line['naive_hfrac'] == '' else float(line['naive_hfrac'])  # we need the singletons, even if they don't have hfracs
            else:
                assert False

            unique_ids = line['unique_ids'].split(':')

            if not utils.from_same_event(reco_info, unique_ids):
                continue

            if len(unique_ids) == 1:
                singletons.append(line['unique_ids'])
            elif len(unique_ids) == 2:
                pairs.append(line['unique_ids'])  # use the string so it's obvious which order to use when looking in the cache
            elif len(unique_ids) == 3:
                triplets.append(line['unique_ids'])  # use the string so it's obvious which order to use when looking in the cache
            elif len(unique_ids) == 4:
                quads.append(line['unique_ids'])  # use the string so it's obvious which order to use when looking in the cache
            # iline += 1
            # if iline > 10:
            #     break

    baseplotdir = os.getenv('www') + '/partis/clustering/' + label + '/distances'
    if args.dont_normalize:
        baseplotdir += '/nope'
    else:
        baseplotdir += '/normalized'
    if args.logaxis:
        baseplotdir += '/log'
    else:
        baseplotdir += '/nope'
    if args.zoom:
        baseplotdir += '/zoom'
    else:
        baseplotdir += '/nope'

    plotname = leafmutstr(args, n_leaves, mut_mult)

    print 'singletons'
    make_a_distance_plot(args, metric, itertools.combinations(singletons, 2), reco_info, cachevals, plotdir=baseplotdir + '/' + metric + '/singletons', plotname=plotname, plottitle=get_title(args, label, n_leaves, mut_mult) + ' (singletons)')

    print 'one pair one singleton'
    one_pair_one_singleton = []
    for ipair in range(len(pairs)):
        for ising in range(len(singletons)):
            one_pair_one_singleton.append((pairs[ipair], singletons[ising]))
    make_a_distance_plot(args, metric, one_pair_one_singleton, reco_info, cachevals, plotdir=baseplotdir + '/' + metric + '/one-pair-one-singleton', plotname=plotname, plottitle=get_title(args, label, n_leaves, mut_mult) + ' (pair + single)')

    print 'one triplet one singleton'
    one_triplet_one_singleton = []
    for itriplet in range(len(triplets)):
        for ising in range(len(singletons)):
            one_triplet_one_singleton.append((triplets[itriplet], singletons[ising]))
    make_a_distance_plot(args, metric, one_triplet_one_singleton, reco_info, cachevals, plotdir=baseplotdir + '/' + metric + '/one-triplet-one-singleton', plotname=plotname, plottitle=get_title(args, label, n_leaves, mut_mult) + ' (triple + single)')

    print 'one quad one singleton'
    one_quad_one_singleton = []
    for iquad in range(len(quads)):
        for ising in range(len(singletons)):
            one_quad_one_singleton.append((quads[iquad], singletons[ising]))
    make_a_distance_plot(args, metric, one_quad_one_singleton, reco_info, cachevals, plotdir=baseplotdir + '/' + metric + '/one-quad-one-singleton', plotname=plotname, plottitle=get_title(args, label, n_leaves, mut_mult) + ' (quad + single)')

    # print 'two pairs'
    # two_pairs = []
    # for ipair in range(len(pairs)):
    #     for jpair in range(ipair + 1, len(pairs)):
    #         two_pairs.append((pairs[ipair], pairs[jpair]))
    # make_a_distance_plot(args, metric, two_pairs, reco_info, cachevals, plotdir=baseplotdir + '/' + metric + '/two-pairs', plotname=plotname, plottitle=get_title(args, label, n_leaves, mut_mult) + ' (pair + pair)')

    # print 'two triplets'
    # two_triplets = []
    # for itriplet in range(len(triplets)):
    #     for jtriplet in range(itriplet + 1, len(triplets)):
    #         two_triplets.append((triplets[itriplet], triplets[jtriplet]))
    # make_a_distance_plot(args, metric, two_triplets, reco_info, cachevals, plotdir=baseplotdir + '/' + metric + '/two-triplets', plotname=plotname, plottitle=get_title(args, label, n_leaves, mut_mult) + ' (triplet + triplet)')

# ----------------------------------------------------------------------------------------
def write_all_plot_csvs(args, label):
    hists, adj_mis, ccfs, partitions = {}, {}, {}, {}
    for n_leaves in args.n_leaf_list:
        for mut_mult in args.mutation_multipliers:
            print n_leaves, mut_mult
            write_each_plot_csvs(args, label, n_leaves, mut_mult, hists, adj_mis, ccfs, partitions)

# ----------------------------------------------------------------------------------------
def write_each_plot_csvs(args, label, n_leaves, mut_mult, hists, adj_mis, ccfs, partitions):
    if n_leaves not in hists:
        hists[n_leaves] = {}
        adj_mis[n_leaves] = {}
        ccfs[n_leaves] = {}
        partitions[n_leaves] = {}
    if mut_mult not in hists[n_leaves]:
        hists[n_leaves][mut_mult] = OrderedDict()
        adj_mis[n_leaves][mut_mult] = OrderedDict()
        ccfs[n_leaves][mut_mult] = OrderedDict()
        partitions[n_leaves][mut_mult] = OrderedDict()
    these_hists = hists[n_leaves][mut_mult]
    these_adj_mis = adj_mis[n_leaves][mut_mult]
    these_ccfs = ccfs[n_leaves][mut_mult]
    these_partitions = partitions[n_leaves][mut_mult]

    plotdir = os.getenv('www') + '/partis/clustering/subsets/' + label
    if args.subset is not None:
        plotdir += '/subset-' + str(args.subset)
    if args.istartstop is not None:
        plotdir += '/istartstop-' + '-'.join([str(i) for i in args.istartstop])
    if args.data:
        seqfname = get_simfname(args, label, n_leaves, mut_mult).replace(leafmutstr(args, n_leaves, mut_mult), 'data')  # hackey hackey hackey
        simfbase = None
        csvdir = os.path.dirname(seqfname) + '/data'
        plotname = 'data'
        title = get_title(args, label, n_leaves, mut_mult)
    else:
        seqfname = get_simfname(args, label, n_leaves, mut_mult)
        simfbase = leafmutstr(args, n_leaves, mut_mult)
        csvdir = os.path.dirname(seqfname) + '/' + simfbase
        plotname = simfbase
        title = get_title(args, label, n_leaves, mut_mult)

    _, reco_info = seqfileopener.get_seqfile_info(seqfname, is_data=args.data)
    if args.count_distances:
        make_distance_plots(args, label, n_leaves, mut_mult, seqfname.replace('.csv', '-partition-cache.csv'), reco_info, 'naive_hfrac')  #logprob')  #'')
        return

    rebin = None
    # if n_leaves > 10:
    #     rebin = 2

    # vollmers annotation (and true hists)
    parse_vollmers(args, these_hists, these_adj_mis, these_ccfs, these_partitions, seqfname, csvdir, reco_info, rebin=rebin)

    if not args.no_mixcr:
        parse_mixcr(args, these_hists, these_adj_mis, these_ccfs, seqfname, csvdir)

    if not args.no_changeo:
        parse_changeo(args, label, n_leaves, mut_mult, these_hists, these_adj_mis, these_ccfs, these_partitions, simfbase, csvdir, rebin=rebin)

    # partis stuff
    for ptype in ['vsearch-', 'naive-hamming-', '']:
    # for ptype in ['vsearch-']:
        parse_partis(args, ptype + 'partition', these_hists, these_adj_mis, these_ccfs, these_partitions, seqfname, csvdir, reco_info, rebin=rebin)

    log = 'xy'
    if not args.data and n_leaves <= 10:
        log = 'x'
    plotting.plot_cluster_size_hists(plotdir + '/' + plotname + '.svg', these_hists, title=title, log=log)  #, xmax=n_leaves*6.01
    # for meth1, meth2 in itertools.combinations(these_partitions.keys(), 2):
    #     if '0.5' in meth1 or '0.5' in meth2:  # skip vollmers 0.5
    #         continue
    #     n_biggest_clusters = 40  # if args.data else 30)
    #     plotting.plot_cluster_similarity_matrix(plotdir + '/' + (meth1 + '-' + meth2).replace('partition ', ''), plotname, meth1, these_partitions[meth1], meth2, these_partitions[meth2], n_biggest_clusters=n_biggest_clusters, title=get_title(args, label, n_leaves, mut_mult))
    # # check_call(['./bin/permissify-www', plotdir])

# ----------------------------------------------------------------------------------------
def convert_adj_mi_and_co_to_plottable(args, valdict, mut_mult_to_use):
    plotvals = OrderedDict()
    for n_leaves in args.n_leaf_list:
        for meth, (val, err) in valdict[n_leaves][mut_mult_to_use].items():
            if meth not in plotvals:
                plotvals[meth] = OrderedDict()
            plotvals[meth][n_leaves] = val, err
    return plotvals

# ----------------------------------------------------------------------------------------
def compare_all_subsets(args, label):
    hists, adj_mis, ccf_unders, ccf_overs = {}, {}, {}, {}
    for n_leaves in args.n_leaf_list:
        print '%d leaves' % n_leaves
        for mut_mult in args.mutation_multipliers:
            print '  %.1f mutation' % mut_mult
            compare_each_subsets(args, label, n_leaves, mut_mult, hists, adj_mis, ccf_unders, ccf_overs)

    if not args.data:
        for mut_mult in args.mutation_multipliers:
            plotvals = convert_adj_mi_and_co_to_plottable(args, adj_mis, mut_mult)
            plotting.plot_adj_mi_and_co(plotvals, mut_mult, os.getenv('www') + '/partis/clustering/subsets/' + label, 'adj_mi')

            plotvals = convert_adj_mi_and_co_to_plottable(args, ccf_unders, mut_mult)
            plotting.plot_adj_mi_and_co(plotvals, mut_mult, os.getenv('www') + '/partis/clustering/subsets/' + label, 'ccf_under')
            plotvals = convert_adj_mi_and_co_to_plottable(args, ccf_overs, mut_mult)
            plotting.plot_adj_mi_and_co(plotvals, mut_mult, os.getenv('www') + '/partis/clustering/subsets/' + label, 'ccf_over')

# ----------------------------------------------------------------------------------------
def compare_each_subsets(args, label, n_leaves, mut_mult, hists, adj_mis, ccf_unders, ccf_overs):
    if n_leaves not in hists:
        hists[n_leaves] = {}
        adj_mis[n_leaves] = {}
        ccf_unders[n_leaves] = {}
        ccf_overs[n_leaves] = {}
    if mut_mult not in hists[n_leaves]:
        hists[n_leaves][mut_mult] = OrderedDict()
        adj_mis[n_leaves][mut_mult] = OrderedDict()
        ccf_unders[n_leaves][mut_mult] = OrderedDict()
        ccf_overs[n_leaves][mut_mult] = OrderedDict()
    these_hists = hists[n_leaves][mut_mult]
    these_vals = {}
    these_vals['adj_mi'] = adj_mis[n_leaves][mut_mult]
    these_vals['ccf_under'] = ccf_unders[n_leaves][mut_mult]
    these_vals['ccf_over'] = ccf_overs[n_leaves][mut_mult]

    basedir = args.fsdir + '/' + label
    # all of 'em:
    expected_methods = ['vollmers-0.9', 'mixcr', 'changeo', 'vsearch-partition', 'naive-hamming-partition', 'partition']  # mostly so we can specify the order
    if args.no_mixcr:
        expected_methods.remove('mixcr')
    if args.no_changeo:
        expected_methods.remove('changeo')
    if not args.data:
        expected_methods.insert(0, 'true')
    tmp_valdicts = {'adj_mi' : OrderedDict(), 'ccf_under' : OrderedDict(), 'ccf_over' : OrderedDict()}
    for method in expected_methods:
        method_hists = []
        if args.n_subsets is not None:
            subdirs = [basedir + '/subset-' + str(isub) for isub in range(args.n_subsets)]
        elif args.startstoplist is not None:
            subdirs = [basedir + '/istartstop-' + istartstop.replace(',', '-') for istartstop in args.startstoplist]
        else:
            assert False
        for subdir in subdirs:
            # hists
            if args.data:
                histfname = subdir + '/data/hists/' + method + '.csv'
            else:
                histfname = subdir + '/' + leafmutstr(args, n_leaves, mut_mult) + '/hists/' + method + '.csv'
            method_hists.append(Hist(fname=histfname))
            if method == 'true':
                continue

            if not args.data:
                for valname in tmp_valdicts:
                    if n_leaves == 1 and valname == 'adj_mi':
                        continue
                    fname = subdir + '/' + leafmutstr(args, n_leaves, mut_mult) + '/' + valname+ '/' + method + '.csv'
                    if method not in tmp_valdicts[valname]:
                        tmp_valdicts[valname][method] = []
                    tmp_valdicts[valname][method].append(read_float_val(fname, valname))

        these_hists[method] = plotting.make_mean_hist(method_hists)

    plotdir = os.getenv('www') + '/partis/clustering/subsets/' + label
    log = 'xy'
    if args.data:
        title = get_title(args, label, n_leaves, mut_mult)
        plotfname = plotdir + '/plots/data.svg'
        xmax = 10
    else:
        title = get_title(args, label, n_leaves, mut_mult)
        plotfname = plotdir + '/plots/' + leafmutstr(args, n_leaves, mut_mult) + '.svg'
        xmax = n_leaves*6.01
        if n_leaves <= 10:
            log = 'x'
    plotting.plot_cluster_size_hists(plotfname, these_hists, title=title, xmax=xmax, log=log)
    check_call(['./bin/makeHtml', plotdir, '3', 'null', 'svg'])
    check_call(['./bin/permissify-www', plotdir])

    if not args.data:
        for valname in tmp_valdicts:
            print '   ', valname
            # plotting.plot_adj_mi_and_co(tmp_valdicts[valname])
            for meth, vals in tmp_valdicts[valname].items():
                mean = numpy.mean(vals)
                if mean == -1.:
                    continue
                std = numpy.std(vals)
                these_vals[valname][meth] = (mean, std)
                print '        %30s %.3f +/- %.3f' % (meth, mean, std)

# ----------------------------------------------------------------------------------------
def get_misassigned_adj_mis(simfname, misassign_fraction, nseq_list, error_type):
    input_info, reco_info = seqfileopener.get_seqfile_info(simfname, is_data=False)
    n_reps = 1
    uid_list = input_info.keys()
    new_partitions = {}
    for nseqs in nseq_list:
        for irep in range(n_reps):  # repeat <nreps> times
            istart = irep * nseqs
            istop = istart + nseqs
            uids = uid_list[istart : istop]
            true_partition = utils.get_true_partition(reco_info, ids=uids)
            n_misassigned = int(misassign_fraction * nseqs)
            new_partition = generate_incorrect_partition(true_partition, n_misassigned, error_type=error_type)
            # new_partition = generate_incorrect_partition(true_partition, n_misassigned, error_type='singletons')
            new_partitions[nseqs] = new_partition
    return {nseqs : utils.adjusted_mutual_information(new_partitions[nseqs], utils.get_true_partition(reco_info, ids=new_partitions[nseqs].keys())) for nseqs in nseq_list}

# ----------------------------------------------------------------------------------------
def make_adj_mi_vs_sample_size_plot(args, label, n_leaves, mut_mult, nseq_list, adj_mis):
    import matplotlib as mpl
    mpl.use('Agg')
    import matplotlib.pyplot as plt
    import seaborn as sns
    sns.set_style('ticks')
    fsize = 20
    mpl.rcParams.update({
        # 'font.size': fsize,
        'legend.fontsize': fsize,
        'axes.titlesize': fsize,
        # 'axes.labelsize': fsize,
        'xtick.labelsize': fsize,
        'ytick.labelsize': fsize,
        'axes.labelsize': fsize
    })
    fig, ax = plt.subplots()
    fig.tight_layout()
    plt.gcf().subplots_adjust(bottom=0.16, left=0.2, right=0.78, top=0.95)

    plots = {}

    colors = {'vsearch-partition' : '#008b8b',
              'naive-hamming-partition' : '#ff8c00',
              'partition' : '#cc0000',
              '0.1-true-singletons' : '#006600',
              '0.1-true-reassign' : '#32cd32'}
    adj_mis['0.1-true-singletons'] = get_misassigned_adj_mis(get_simfname(args, label, n_leaves, mut_mult), 0.1, nseq_list, 'singletons')
    adj_mis['0.1-true-reassign'] = get_misassigned_adj_mis(get_simfname(args, label, n_leaves, mut_mult), 0.1, nseq_list, 'reassign')
    for meth in adj_mis:
        linewidth = 2
        linestyle = '-'
        if 'true' in meth:
            linewidth = 4
            linestyle = '--'
        plots[meth] = ax.plot(nseq_list, [adj_mis[meth][ns] for ns in nseq_list], linewidth=linewidth, label=plotting.legends.get(meth, meth), color=colors.get(meth, 'grey'), linestyle=linestyle, alpha=1)
        if 'true' not in meth:
            plt.scatter(nseq_list, [adj_mis[meth][ns] for ns in nseq_list], color=colors.get(meth, 'grey'), linestyle='-', alpha=1, s=[30 for _ in range(len(nseq_list))])

    legend = ax.legend(loc=(0.55, 0.1))
    sns.despine(trim=True, bottom=True)
    plt.title('%d leaves, %dx mutation' % (n_leaves, mut_mult))
    plt.xlabel('sample size')
    plt.ylabel('adjusted MI')
    plt.subplots_adjust(bottom=0.14, left=0.14)
    ax.set_xscale('log')
    xmin, xmax = nseq_list[0], nseq_list[-1] + 10
    plt.xlim(xmin, xmax)
    plt.ylim(0, 1.08)
    potential_xticks = [5, 10, 25, 50, 100, 300, 1000]
    xticks = [xt for xt in potential_xticks if xt < xmax]
    plt.xticks(xticks, [str(xt) for xt in xticks])
    plotdir = os.getenv('www') + '/partis/clustering/sample-sizes/' + label
    outfname = plotdir + '/plots/sample-sizes.svg'
    if not os.path.exists(plotdir + '/plots'):
        os.makedirs(plotdir + '/plots')
    plt.savefig(outfname)
    check_call(['./bin/makeHtml', plotdir, '3', 'null', 'svg'])
    check_call(['./bin/permissify-www', plotdir])

    return

# ----------------------------------------------------------------------------------------
def compare_sample_sizes(args, label, n_leaves, mut_mult):
    """ see sample-size-partition.py """
    raise Exception('It is possible that I may have broken this')
    expected_methods = ['vsearch-partition', 'naive-hamming-partition', 'partition']  # mostly so we can specify the order
    # expected_methods = ['vollmers-0.9', 'partition']  # mostly so we can specify the order
    basedir = args.fsdir + '/' + label
    nseq_list = []
    adj_mis, hists = OrderedDict(), OrderedDict()
    for meth in expected_methods:
        adj_mis[meth], hists = {}, {}
    # for dirname in glob.glob(basedir + '/istartstop-*'):
    #     dumstr, istart, istop = dirname.split('/')[-1].split('-')
    #     istart, istop = int(istart), int(istop)
    for istartstop in args.startstoplist:
        istart, istop = [int(i) for i in istartstop.split(',')]
        nseqs = istop - istart
        dirname = basedir + '/istartstop-' + str(istart) + '-' + str(istop)
        nseq_list.append(nseqs)
        for meth in expected_methods:
            action = meth
            if 'vollmers' in meth:
                action = 'run-viterbi'
            if args.data:
                csvfname = dirname + '/data' + '-' + action + '.csv'
            else:
                csvfname = dirname + '/' + leafmutstr(args, n_leaves, mut_mult) + '-' + action + '.csv'
            cpath = ClusterPath()
            cpath.readfile(csvfname)
            if not args.data:  # why the hell was this "not" missing?
                adj_mis[meth][nseqs] = cpath.adj_mis[cpath.i_best]
            hists[meth][nseqs] = plotting.get_cluster_size_hist(cpath.partitions[cpath.i_best])

    nseq_list.sort()

    if not args.data:
        make_adj_mi_vs_sample_size_plot(args, label, n_leaves, mut_mult, nseq_list, adj_mis)

    mean_hists = OrderedDict()
    for meth in expected_methods:
        mean_hists[meth] = plotting.make_mean_hist(hists[meth])
    plotdir = os.getenv('www') + '/partis/clustering/' + label
    log = 'xy'
    if args.data:
        plotfname = plotdir + '/plots/data.svg'
        title = get_title(args, label, n_leaves, mut_mult)
        xmax = None
    else:
        raise Exception('what was simfbase supposed to be here?')
        plotfname = plotdir + '/plots/' + simfbase + '.svg'
        title = get_title(args, label, n_leaves, mut_mult)
        xmax = n_leaves*3.01
        if n_leaves <= 10:
            log = 'x'
    plotting.plot_cluster_size_hists(plotfname, mean_hists, title=title, xmax=xmax, log=log)

# ----------------------------------------------------------------------------------------
def output_exists(args, outfname):
    if os.path.exists(outfname):
        if os.stat(outfname).st_size == 0:
            print '                      deleting zero length %s' % outfname
            os.remove(outfname)
            return False
        elif args.overwrite:
            print '                      overwriting %s' % outfname
            if os.path.isdir(outfname):
                raise Exception('output %s is a directory, rm it by hand' % outfname)
            else:
                os.remove(outfname)
            return False
        else:
            print '                      output exists, skipping (%s)' % outfname
            return True
    else:
        return False

# ----------------------------------------------------------------------------------------
def run_changeo(args, label, n_leaves, mut_mult, seqfname):
    def untar_imgt(imgtdir):
        tar_cmd = 'mkdir ' + imgtdir + ';'
        tar_cmd += ' tar Jxvf ' + imgtdir + '.txz --exclude=\'IMGT_HighV-QUEST_individual_files_folder/*\' -C ' + imgtdir
        check_call(tar_cmd, shell=True)

    imgtdir = get_changeo_outdir(args, label, n_leaves, mut_mult)
    if os.path.isdir(imgtdir):
        print '                      already untar\'d into %s' % imgtdir
    else:
        if os.path.exists(imgtdir + '.txz'):
            untar_imgt(imgtdir)
        else:
            print '   hmm... imgtdir not there... maybe we only have the subsets'

    if args.subset is not None:
        subset_dir = imgtdir + '/subset-' + str(args.subset)
        if not os.path.exists(subset_dir):
            os.makedirs(subset_dir)
            tsvfnames = glob.glob(imgtdir + '/*.txt')
            check_call(['cp', '-v', imgtdir + '/11_Parameters.txt', subset_dir + '/'])
            tsvfnames.remove(imgtdir + '/11_Parameters.txt')
            tsvfnames.remove(imgtdir + '/README.txt')
            input_info, reco_info = seqfileopener.get_seqfile_info(seqfname, is_data=False)
            subset_ids = input_info.keys()
            utils.subset_files(subset_ids, tsvfnames, subset_dir)
        imgtdir = subset_dir
    if args.istartstop is not None:
        subset_dir = imgtdir + '/istartstop_' + '_'.join([str(i) for i in args.istartstop])
        if os.path.exists(subset_dir + '.txz'):
            untar_imgt(subset_dir)
        elif not os.path.exists(subset_dir):
            os.makedirs(subset_dir)
            tsvfnames = glob.glob(imgtdir + '/*.txt')
            check_call(['cp', '-v', imgtdir + '/11_Parameters.txt', subset_dir + '/'])
            tsvfnames.remove(imgtdir + '/11_Parameters.txt')
            tsvfnames.remove(imgtdir + '/README.txt')
            input_info, reco_info = seqfileopener.get_seqfile_info(seqfname, is_data=args.data)
            subset_ids = input_info.keys()
            utils.subset_files(subset_ids, tsvfnames, subset_dir)
        imgtdir = subset_dir

    def run(cmdstr):
        print 'RUN %s' % cmdstr
        check_call(cmdstr.split())

    resultfname = imgtdir + changeorandomcrapstr
    if output_exists(args, resultfname):
        return

    fastafname = os.path.splitext(seqfname)[0] + '.fasta'
    utils.csv_to_fasta(seqfname, outfname=fastafname)  #, name_column='name' if args.data else 'unique_id', seq_column='nucleotide' if args.data else 'seq')
    bindir = '/home/dralph/work/changeo/changeo'
    start = time.time()
    cmd = bindir + '/MakeDb.py imgt -i ' + imgtdir + ' -s ' + fastafname
    run(cmd)
    cmd = bindir + '/ParseDb.py select -d ' + imgtdir + '_db-pass.tab -f FUNCTIONAL -u T'
    run(cmd)
    # cmd = bindir + '/DefineClones.py bygroup -d ' + imgtdir + '_db-pass_parse-select.tab --act first --model m1n --dist 7'
    cmd = bindir + '/DefineClones.py bygroup -d ' + imgtdir + '_db-pass_parse-select.tab --model hs1f --norm len --act set --dist 0.2'
    run(cmd)
    print '        changeo time: %.3f' % (time.time()-start)

    # read changeo's output and toss it into a csv
    input_info, reco_info = seqfileopener.get_seqfile_info(seqfname, is_data=args.data)
    id_clusters = {}  # map from cluster id to list of seq ids
    with open(resultfname) as chfile:
        reader = csv.DictReader(chfile, delimiter='\t')
        for line in reader:
            clid = line['CLONE']
            uid = line['SEQUENCE_ID']
            if clid not in id_clusters:
                id_clusters[clid] = []
            id_clusters[clid].append(uid)

    partition = [ids for ids in id_clusters.values()]
    # these_hists['changeo'] = plotting.get_cluster_size_hist(partition)
    if not args.data:
        write_float_val(imgtdir + '-adj_mi.csv', utils.adjusted_mutual_information(partition, utils.get_true_partition(reco_info)), 'adj_mi')
        ccfs = utils.correct_cluster_fractions(partition, reco_info)
        write_float_val(imgtdir + '-ccf_under.csv', ccfs[0], 'ccf_under')
        write_float_val(imgtdir + '-ccf_over.csv', ccfs[1], 'ccf_over')

# ----------------------------------------------------------------------------------------
def run_mixcr(args, label, n_leaves, mut_mult, seqfname):
    binary = '/home/dralph/work/mixcr/mixcr-1.2/mixcr'
    mixcr_workdir = get_program_workdir(args, 'mixcr', label, n_leaves, mut_mult)
    if not os.path.exists(mixcr_workdir):
        os.makedirs(mixcr_workdir)

    # fastafname = os.path.splitext(seqfname)[0] + '.fasta'
    infname = mixcr_workdir + '/' + os.path.basename(os.path.splitext(seqfname)[0] + '.fasta')
    outfname = os.path.splitext(seqfname)[0] + '-mixcr.tsv'
    if output_exists(args, outfname):
        return

    # check_call(['./bin/csv2fasta', seqfname])
    utils.csv_to_fasta(seqfname, outfname=infname, n_max_lines=args.n_to_partition)  #, name_column='name' if args.data else 'unique_id', seq_column='nucleotide' if args.data else 'seq'
    # check_call('head -n' + str(2*args.n_to_partition) + ' ' + fastafname + ' >' + infname, shell=True)
    # os.remove(seqfname.replace('.csv', '.fa'))

    def run(cmdstr):
        print 'RUN %s' % cmdstr
        check_call(cmdstr.split())

    start = time.time()
    cmd = binary + ' align -f --loci IGH ' + infname + ' ' + infname.replace('.fasta', '.vdjca')
    run(cmd)
    cmd = binary + ' assemble -f ' + infname.replace('.fasta', '.vdjca') + ' ' + infname.replace('.fasta', '.clns')
    run(cmd)
    cmd = binary + ' exportClones ' + infname.replace('.fasta', '.clns') + ' ' + infname.replace('.fasta', '.txt')
    run(cmd)
    print '        mixcr time: %.3f' % (time.time()-start)
    check_call(['cp', '-v', infname.replace('.fasta', '.txt'), outfname])


# ----------------------------------------------------------------------------------------
def run_igscueal(args, label, n_leaves, mut_mult, seqfname):
    igscueal_dir = '/home/dralph/work/IgSCUEAL'
    # outfname = os.path.splitext(seqfname)[0] + '-igscueal.tsv'
    # if output_exists(args, outfname):
    #     return
    workdir = get_program_workdir(args, 'igscueal', label, n_leaves, mut_mult)

    infname = workdir + '/' + os.path.basename(os.path.splitext(seqfname)[0] + '.fasta')

    if not os.path.exists(workdir):
        os.makedirs(workdir)

    utils.csv_to_fasta(seqfname, outfname=infname, n_max_lines=args.n_to_partition)  #, name_column='name' if args.data else 'unique_id', seq_column='nucleotide' if args.data else 'seq'
    # write cfg file (.bf)
    sed_cmd = 'sed'
    replacements = {'igscueal_dir' : igscueal_dir,
                    'input_fname' : infname,
                    'results_fname' : workdir + '/results.tsv',
                    'rearrangement_fname' : workdir + '/rearrangement.tsv',
                    'tree_assignment_fname' : workdir + '/tree_assignment.tsv'}
    for pattern, replacement in replacements.items():
        sed_cmd += ' -e \'s@xxx-' + pattern + '-xxx@' + replacement + '@\''
    template_cfgfname = igscueal_dir + '/TopLevel/MPIScreenFASTA.bf'
    cfgfname = workdir + '/cfg.bf'
    sed_cmd += ' ' + template_cfgfname + ' >' + cfgfname
    check_call(sed_cmd, shell=True)

    # cmd = 'salloc -N 3 mpirun -np 3 /home/dralph/work/hyphy/hyphy-master/HYPHYMPI ' + cfgfname
    # srun --mpi=openmpi
    cmd = 'srun --exclude=data/gizmod.txt mpirun -np 2 /home/dralph/work/hyphy/hyphy-master/HYPHYMPI ' + cfgfname

    ntot = int(check_output(['wc', '-l', infname]).split()[0]) / 2
    n_procs = max(1, int(float(ntot) / 10))
    n_per_proc = int(float(ntot) / n_procs)  # NOTE ignores remainders, i.e. last few sequences
    workdirs = []
    start = time.time()
    procs = []
    for iproc in range(n_procs):
        workdirs.append(workdir + '/igs-' + str(iproc))
        if not os.path.exists(workdirs[-1]):
            os.makedirs(workdirs[-1])

        if len(procs) - procs.count(None) > 500:  # can't have more open files than something like this
            print '        too many procs (len %d    none %d)' % (len(procs), procs.count(None))
            procs.append(None)
            continue

        suboutfname = replacements['results_fname'].replace(workdir, workdirs[-1])
        if os.path.exists(suboutfname) and os.stat(suboutfname).st_size != 0:
            print '    %d already there (%s)' % (iproc, suboutfname)
            procs.append(None)
            continue

        check_call(['cp', cfgfname, workdirs[-1] + '/'])
        check_call(['sed', '-i', 's@' + workdir + '@' + workdirs[-1] + '@', workdirs[-1] + '/' + os.path.basename(cfgfname)])

        subinfname = workdirs[-1] + '/' + os.path.basename(infname)
        istart = 2 * iproc * n_per_proc + 1  # NOTE sed indexing (one-indexed with inclusive bounds), and factor of two for fasta file
        istop = istart + 2 * n_per_proc - 1
        check_call('sed -n \'' + str(istart) + ',' + str(istop) + ' p\' ' + infname + '>' + subinfname, shell=True)

        print '     starting %d' % iproc
        procs.append(Popen(cmd.replace(workdir, workdirs[-1]).split(), stdout=PIPE, stderr=PIPE))
        # procs.append(Popen(['sleep', '10']))

    while procs.count(None) < len(procs):
        for iproc in range(n_procs):
            if procs[iproc] is not None and procs[iproc].poll() is not None:  # it's finished
                stdout, stderr = procs[iproc].communicate()
                print '\nproc %d' % iproc
                print 'out----\n', stdout, '\n-----'
                print 'err----\n', stderr, '\n-----'
                procs[iproc] = None
            time.sleep(0.1)
    print '      igscueal time: %.3f' % (time.time()-start)

# ----------------------------------------------------------------------------------------
def slice_file(args, csv_infname, csv_outfname):  # not necessarily csv
    if os.path.exists(csv_outfname):
        utils.csv_to_fasta(csv_outfname)  #, name_column='name' if args.data else 'unique_id', seq_column='nucleotide' if args.data else 'seq')
        print '      slicefile exists %s' % csv_outfname
        return
    print '      subsetting %d seqs with indices %d --> %d' % (args.istartstop[1] - args.istartstop[0], args.istartstop[0], args.istartstop[1])
    if not os.path.exists(os.path.dirname(csv_outfname)):
        os.makedirs(os.path.dirname(csv_outfname))
    if '.csv' in csv_infname:  # if it's actually a csv
        remove_csv_infname = False
        check_call('head -n1 ' + csv_infname + ' >' + csv_outfname, shell=True)
        check_call('sed -n \'' + str(args.istartstop[0] + 2) + ',' + str(args.istartstop[1] + 1) + ' p\' ' + csv_infname + '>>' + csv_outfname, shell=True)  # NOTE conversion from standard zero indexing to sed inclusive one-indexing (and +1 for header line)
        if remove_csv_infname:
            assert '/dralph/' in csv_infname
            os.remove(csv_infname)
    elif '.fa' in csv_infname:
        input_info, _ = seqfileopener.get_seqfile_info(csv_infname, is_data=True)
        with open(csv_outfname, 'w') as outfile:
            writer = csv.DictWriter(outfile, ('unique_id', 'seq'))
            writer.writeheader()
            iseq = -1
            for line in input_info.values():  # hackey, but it's an ordered dict so it should be ok
                iseq += 1
                if iseq < args.istartstop[0]:
                    continue
                if iseq >= args.istartstop[1]:
                    break
                writer.writerow({'unique_id' : line['unique_id'], 'seq' : line['seq']})
        # print 'sed -n \'' + str(2*args.istartstop[0] + 1) + ',' + str(2*args.istartstop[1] + 1) + ' p\' ' + csv_infname + '>>' + csv_outfname
        # check_call('sed -n \'' + str(2*args.istartstop[0] + 1) + ',' + str(2*args.istartstop[1] + 1) + ' p\' ' + csv_infname + '>>' + csv_outfname, shell=True)  # NOTE conversion from standard zero indexing to sed inclusive one-indexing (and multiply by two for fasta file)

# ----------------------------------------------------------------------------------------
def get_seqfile(args, datafname, label, n_leaves, mut_mult):

    if args.data:
        if args.istartstop is None:
            seqfname = datafname
        else:
            subfname = args.fsdir + '/' + label + '/istartstop-' + '-'.join([str(i) for i in args.istartstop]) + '/data.csv'
            slice_file(args, datafname, subfname)
            seqfname = subfname
    else:
        if not args.data:
            assert n_leaves is not None and mut_mult is not None
        simfname = get_simfname(args, label, n_leaves, mut_mult, no_subset=True)

        if args.subset is not None:
            ntot = int(check_output(['wc', '-l', simfname]).split()[0]) - 1
            subsimfname = simfname.replace(label + '/', label + '/subset-' + str(args.subset) + '/')
            if os.path.exists(subsimfname):
                print '      subset file exists %s' % subsimfname
            else:
                print '      subsetting %d / %d' % (args.subset, args.n_subsets)
                if not os.path.exists(os.path.dirname(subsimfname)):
                    os.makedirs(os.path.dirname(subsimfname))
                check_call('head -n1 ' + simfname + ' >' + subsimfname, shell=True)
                n_per_subset = int(float(ntot) / args.n_subsets)  # NOTE ignores remainders, i.e. last few sequences
                istart = args.subset * n_per_subset + 2  # NOTE sed indexing (one-indexed with inclusive bounds). Also note extra +1 to avoid header
                istop = istart + n_per_subset - 1
                check_call('sed -n \'' + str(istart) + ',' + str(istop) + ' p\' ' + simfname + '>>' + subsimfname, shell=True)
            simfname = subsimfname

        if args.istartstop is not None:
            subsimfname = simfname.replace(label + '/', label + '/istartstop-' + '-'.join([str(i) for i in args.istartstop]) + '/')
            slice_file(args, simfname, subsimfname)
            simfname = subsimfname

        seqfname = simfname

    return seqfname

# ----------------------------------------------------------------------------------------
def execute(args, action, datafname, label, n_leaves, mut_mult, procs):
    cmd = './bin/run-driver.py --label ' + label + ' --action '
    if 'partition' in action:
        cmd += ' partition'
    else:
        cmd += ' ' + action
    cmd += ' --stashdir ' + args.fsdir + ' --old-style-dir-structure'

    extras = []
    seqfname = get_seqfile(args, datafname, label, n_leaves, mut_mult)
    if args.data:
        cmd += ' --datafname ' + seqfname + ' --is-data'
        if args.dataset == 'adaptive':
            extras += ['--skip-unproductive', ]
    else:
        cmd += ' --simfname ' + seqfname

    def get_outputname():
        if args.data:
            return get_outdirname(args, label) + '/data-' + action + '.csv'
        else:
            return ('-' + action).join(os.path.splitext(seqfname))

    n_procs, n_fewer_procs = 1, 1
    if action == 'cache-data-parameters':
        if output_exists(args, args.fsdir + '/' + label + '/data'):
            return
        extras += ['--n-max-queries', + args.n_data_to_cache]
        n_procs = max(1, args.n_data_to_cache / 500)
        n_fewer_procs = min(500, args.n_data_to_cache / 2000)
    elif action == 'simulate':
        if output_exists(args, seqfname):
            return
        extras += ['--n-sim-events', int(float(args.n_sim_seqs) / n_leaves)]
        extras += ['--n-leaves', n_leaves, '--mutation-multiplier', mut_mult]
        if args.indels:
            extras += ['--indel-frequency', 0.5]
        if args.lonely_leaves:
            extras += ['--constant-number-of-leaves', ]
        n_procs = 10
    elif action == 'cache-simu-parameters':
        if output_exists(args, seqfname.replace('.csv', '')):
            return
        n_procs = 20
        n_fewer_procs = min(500, args.n_sim_seqs / 2000)
    elif action == 'partition':
        outfname = get_outputname()
        if output_exists(args, outfname):
            return
        cmd += ' --outfname ' + outfname
        extras += ['--n-max-queries', args.n_to_partition]
        if args.count_distances:
            extras += ['--persistent-cachefname', ('-cache').join(os.path.splitext(outfname))]  # '--n-partition-steps', 1,
        n_procs = max(1, args.n_to_partition / 100)
        n_fewer_procs = min(500, args.n_to_partition / 2000)
    elif action == 'naive-hamming-partition':
        outfname = get_outputname()
        if output_exists(args, outfname):
            return
        cmd += ' --outfname ' + outfname
        extras += ['--n-max-queries', args.n_to_partition, '--naive-hamming']
        n_procs = max(1, args.n_to_partition / 200)
    elif action == 'vsearch-partition':
        outfname = get_outputname()
        if output_exists(args, outfname):
            return
        cmd += ' --outfname ' + outfname
        extras += ['--n-max-queries', args.n_to_partition, '--naive-vsearch']
        n_procs = max(1, args.n_to_partition / 100)  # only used for ighutil step
    elif action == 'run-viterbi':
        outfname = get_outputname()
        if output_exists(args, outfname):
            return
        cmd += ' --outfname ' + outfname
        extras += ['--annotation-clustering', 'vollmers', '--annotation-clustering-thresholds', '0.5:0.9']
        extras += ['--n-max-queries', args.n_to_partition]
        n_procs = max(1, args.n_to_partition / 50)
    elif action == 'run-changeo':
        run_changeo(args, label, n_leaves, mut_mult, seqfname)
        return
    elif action == 'run-mixcr':
        run_mixcr(args, label, n_leaves, mut_mult, seqfname)
        return
    elif action == 'run-igscueal':
        run_igscueal(args, label, n_leaves, mut_mult, seqfname)
        return
    elif action == 'compare-sample-sizes':
        compare_sample_sizes(args, label, n_leaves, mut_mult)
        return
    elif action == 'compare-subsets':
        assert False  # we shouldn't be calling execute() if we're comparing subsets
    else:
        raise Exception('bad action %s' % action)

    # cmd += ' --plotdir ' + os.getenv('www') + '/partis'
    if n_procs > 500:
        print 'reducing n_procs %d --> %d' % (n_procs, 500)
        n_procs = 500
    n_proc_str = str(n_procs)
    extras += ['--workdir', args.fsdir.replace('_output', '_tmp') + '/' + str(random.randint(0, 99999))]
    if n_procs > 10:
        n_fewer_procs = max(1, n_fewer_procs)
        n_proc_str += ':' + str(n_fewer_procs)

    extras += ['--n-procs', n_proc_str]

    cmd += baseutils.get_extra_str(extras)
    print '   ' + cmd
    # return
    # check_call(cmd.split())
    # return
    if args.data:
        logbase = args.fsdir + '/' + label + '/_logs/data-' + action
    else:
        logbase = args.fsdir + '/' + label + '/_logs/' + leafmutstr(args, n_leaves, mut_mult) + '-' + action
    if args.subset is not None:
        logbase = logbase.replace('_logs/', '_logs/subset-' + str(args.subset) + '/')
    if args.istartstop is not None:
        logbase = logbase.replace('_logs/', '_logs/istartstop-' + '-'.join([str(i) for i in args.istartstop]) + '/')
    if not os.path.exists(os.path.dirname(logbase)):
        os.makedirs(os.path.dirname(logbase))
    proc = Popen(cmd.split(), stdout=open(logbase + '.out', 'w'), stderr=open(logbase + '.err', 'w'))
    procs.append(proc)
    # time.sleep(30)  # 300sec = 5min

