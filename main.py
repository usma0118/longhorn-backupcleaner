# Cleanup Longhorn snapshots script by ikaruswill
# ==============
#
# Definitions:
# - Orphaned snapshots: Snapshots created by backup schedules that no longer exist.
# - Stale snapshots: Snapshots that are over n days old
#
# Variables:
# - delete_strings: Delete snapshots that contain any of the strings
#                   To locate orphaned snapshots.
#                   Set to your old backup schedule names
# - delete_age_days: Delete snapshots that are above the specified age in days
#                    To locate stale snapshots.
#                    Set to your oldest possible snapshot (i.e. I have a weekly backup, with Retain = 4, so the oldest snapshot should be 28 days)
#
# Usage:
# 1. Run `kubectl port-forward -n storage services/longhorn-frontend 8080:http`

# Prerequisites:
# 1. longhorn.py from: https://raw.githubusercontent.com/longhorn/longhorn-tests/master/manager/integration/tests/longhorn.py


import datetime
import logging
import threading

import coloredlogs
from decouple import config

import longhorn

# Constants
date_format = '%Y-%m-%dT%H:%M:%SZ'
mib_conversion_factor = 1 / 1024 / 1024
current_date = datetime.datetime.now()

longhorn_url = "http://{}/v1"
longhorn_url=longhorn_url.format(config('LONGHORN_URL'))
delete_age_days = config('DELETE_AGE_DAY', 14)

delete_strings = ['c-6fffho', 'c-b8sdpg','kubestr']


logger = logging.getLogger('Loghorn backup cleaner')
coloredlogs.install(level=config('log_level',default='INFO'),fmt='[%(asctime)s]: %(message)s')

def delete_snapshot(volume, snapshot, reason):
    if snapshot.created:
        created_date = datetime.datetime.strptime(snapshot.created, date_format).strftime('%Y-%m-%d')
    else: created_date=''
    logger.warning('Deleting {reason} snapshot {name} created on {created} with size {size:.1f} MiB'.format(
        name=snapshot.name,
        reason=reason,
        created=created_date,
        size=int(snapshot.size) * mib_conversion_factor
        ))
    try:
        volume.snapshotDelete(name=snapshot.name)
    except longhorn.ApiError as e:
        logger.error('Failed to delete snapshot due to API error: {}'.format(e))



def process_snapshot(volume, snapshot):
    for delete_string in delete_strings:
        if delete_string in snapshot.name:
            delete_snapshot(volume, snapshot, 'orphaned')
            return True
    if snapshot.created:
        snapshot_date = datetime.datetime.strptime(snapshot.created, date_format)
        if (current_date - snapshot_date).days > delete_age_days:
            delete_snapshot(volume, snapshot, 'stale')
            return True
    else:
        logger.debug('Snapshot creation date empty, deleting')
        delete_snapshot(volume, snapshot, 'invalid creation date')
        return True
    logger.warning('Ignoring snapshot: {}'.format(snapshot.name))
    return False


def process_volume(volume):
    logger.info('Processing volume: {} for {} in namespace: {}'.format(volume.name,volume.kubernetesStatus.pvcName, volume.kubernetesStatus.namespace))
    if volume.lastBackup != '':
        logger.info('Last backup: {} on: {}'.format(volume.lastBackup,volume.lastBackupAt))
    try:
        snapshots = volume.snapshotList()
    except AttributeError as e:
        logger.info('Ignoring volume due to AttributeError: {}'.format(e))
        return
    logger.info('Number of snapshots: {}'.format(len(snapshots)))
    deleted_count = 0
    for snapshot in snapshots:
        snapshot_is_deleted = process_snapshot(volume, snapshot)
        if snapshot_is_deleted:
            deleted_count += 1

    if deleted_count > 0:
        logger.info('Purging snapshots...')
        volume.snapshotPurge()

    logger.info('Finished processing volume {}'.format(volume.name))
    logger.error('Deleted {} snapshots'.format(deleted_count))
    volume = client.by_id_volume(id=volume.id)
    logger.info('---')


def process_cluster(client):
    volumes = client.list_volume()
    logger.info('Starting volume snapshot cleanup')
    logger.info('Number of volumes: {}'.format(len(volumes)))

    for i, volume in enumerate(volumes):
        logger.warning('Processing volumeProgress: {:.1f}% ({}/{})'.format(
            i / len(volumes) * 100,i,len(volumes),
            ))
        process_volume(volume)

    logger.info('Finished volume snapshot cleanup')


if __name__ == '__main__':
    client = longhorn.Client(url=longhorn_url)
    threading.current_thread().name = 'longhorn backupCleaner'
    process_cluster(client)
